"""Create blocking calendar events for appointment buffers.

Buffer holds are reconciled from two kinds of trigger:

* an appointment being created / rescheduled / canceled (the protocol handlers
  below), and
* an availability rule being created / updated / deleted (the availability API
  calls ``reconcile_buffers_for_provider`` directly).

Reconciliation always deletes the provider's existing "Buffer" holds first, then
recreates them only when a buffer is still configured on the rule — so removing a
buffer from a rule clears its holds instead of leaving them behind to block
otherwise-bookable slots.

Clinic calendars = open availability (provider IS available).
Administrative calendars = calendar blocks (provider is NOT available).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event as EventEffect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.calendar import Event as EventModel
from logger import log

from provider_availability.engine.admin_calendar import get_admin_calendar_id, get_admin_calendars
from provider_availability.engine.event_sync import DEFAULT_HORIZON_YEARS
from provider_availability.engine.storage import get_rules_for_provider

BUFFER_TITLE = "Buffer"


def _buffer_horizon(now: datetime) -> datetime:
    """The furthest future point we create buffers for, matching availability sync."""
    try:
        return now.replace(year=now.year + DEFAULT_HORIZON_YEARS)
    except ValueError:
        # Feb 29 in a leap year — fall back to Feb 28
        return now.replace(year=now.year + DEFAULT_HORIZON_YEARS, day=now.day - 1)


class OnAppointmentCreated(BaseProtocol):
    """Create buffer events when an appointment is booked."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        return _reconcile_buffers(self.event.target.id, "created")


class OnAppointmentRescheduled(BaseProtocol):
    """Update buffer events when an appointment is rescheduled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_RESCHEDULED)

    def compute(self) -> list[Effect]:
        return _reconcile_buffers(self.event.target.id, "rescheduled")


class OnAppointmentCanceled(BaseProtocol):
    """Remove buffer events when an appointment is canceled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        return _reconcile_buffers(self.event.target.id, "canceled")


def reconcile_buffers_for_provider(provider_id: str, action: str) -> list[Effect]:
    """Reconcile a provider's "Buffer" holds against their current availability rule.

    The delete pass runs first and unconditionally — before the buffer-config check —
    so a removed or zeroed buffer (or a deleted rule) clears the stranded holds it
    left behind. Holds are recreated only when a buffer is still configured.
    """
    effects: list[Effect] = []

    # 1. Delete ALL existing Buffer events on the provider's admin calendars. This
    #    runs regardless of the current buffer config, so removing a buffer from a
    #    rule (or deleting the rule) cleans up the holds it left behind.
    delete_count = 0
    cal_ids = [c.id for c in get_admin_calendars(provider_id)]
    if cal_ids:
        for evt in EventModel.objects.filter(
            calendar__id__in=cal_ids, title=BUFFER_TITLE, is_cancelled=False
        ):
            effects.append(EventEffect(event_id=str(evt.id)).delete())
            delete_count += 1

    rules = get_rules_for_provider(provider_id)
    if not rules:
        log.info("BUFFER: no rules for provider %s — cleared %d buffer events", provider_id, delete_count)
        return effects

    rule = rules[0]
    pre_buffer = rule.buffer_minutes.pre
    post_buffer = rule.buffer_minutes.post

    if pre_buffer == 0 and post_buffer == 0:
        log.info("BUFFER: no buffer configured for provider %s — cleared %d buffer events", provider_id, delete_count)
        return effects

    # 2. A buffer is configured: get or create the Administrative calendar that holds
    #    the recreated buffer events.
    calendar_id, cal_effects = get_admin_calendar_id(provider_id)
    if not calendar_id:
        log.warning("BUFFER: could not resolve Admin calendar for provider %s", provider_id)
        return effects
    effects.extend(cal_effects)

    # 3. Recreate buffer events for future, non-canceled patient appointments.
    #    patient__isnull=False excludes schedule events (lunch, blocks, OOO) — those
    #    are calendar blocks, not visits, and must not spawn buffers. The start_time
    #    ceiling bounds runaway no-end recurring events that would otherwise generate
    #    buffers decades into the future.
    now = datetime.now(UTC)
    appointments = Appointment.objects.filter(
        provider__id=provider_id,
        patient__isnull=False,
        start_time__gte=now,
        start_time__lte=_buffer_horizon(now),
    ).exclude(status="cancelled")

    create_count = 0
    for apt in appointments:
        apt_start = apt.start_time
        apt_end = apt_start + timedelta(minutes=apt.duration_minutes)

        if pre_buffer > 0:
            effects.append(
                EventEffect(
                    calendar_id=calendar_id,
                    title=BUFFER_TITLE,
                    starts_at=apt_start - timedelta(minutes=pre_buffer),
                    ends_at=apt_start,
                ).create()
            )
            create_count += 1

        if post_buffer > 0:
            effects.append(
                EventEffect(
                    calendar_id=calendar_id,
                    title=BUFFER_TITLE,
                    starts_at=apt_end,
                    ends_at=apt_end + timedelta(minutes=post_buffer),
                ).create()
            )
            create_count += 1

    log.info(
        "BUFFER: %s provider %s — deleted %d, created %d buffer events",
        action, provider_id, delete_count, create_count,
    )
    return effects


def _reconcile_buffers(appointment_id: str, action: str) -> list[Effect]:
    """Resolve the triggering appointment's provider and reconcile their buffers."""
    try:
        appt = Appointment.objects.get(id=appointment_id)
    except Appointment.DoesNotExist:
        log.warning("BUFFER: appointment %s not found", appointment_id)
        return []

    if not appt.provider:
        return []

    return reconcile_buffers_for_provider(str(appt.provider.id), action)
