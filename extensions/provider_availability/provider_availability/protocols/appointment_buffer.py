"""Create blocking calendar events for appointment buffers.

When an appointment is created, rescheduled, or canceled, this handler
reconciles "Buffer" events on the provider's Administrative calendar.

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

from provider_availability.engine.admin_calendar import (
    get_admin_calendar_id,
    get_admin_calendars,
    resolve_provider_name,
)
from provider_availability.engine.storage import get_rules_for_provider

BUFFER_TITLE = "Buffer"


def _buffer_title(appointment_id: str) -> str:
    """Buffer event title tagged with the appointment id.

    Encoding the id lets reschedule/cancel find and remove exactly this
    appointment's buffers without re-scanning every appointment (the id is
    stable across reschedules, and Event effects carry no separate metadata
    field, so the title is the only durable link).
    """
    return f"{BUFFER_TITLE}:{appointment_id}"


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


def _reconcile_buffers(appointment_id: str, action: str) -> list[Effect]:
    """Reconcile buffer events for ONE appointment.

    Only this appointment's buffers are touched (found by the id-tagged title),
    so booking/rescheduling N appointments is O(N) total rather than O(N^2) —
    the previous implementation deleted and rebuilt every future appointment's
    buffers on each event.
    """
    try:
        appt = Appointment.objects.get(id=appointment_id)
    except Appointment.DoesNotExist:
        log.warning("BUFFER: appointment %s not found", appointment_id)
        return []

    if not appt.provider:
        return []
    provider_id = str(appt.provider.id)

    rules = get_rules_for_provider(provider_id)
    if not rules:
        log.info("BUFFER: no rules for provider %s, skipping", provider_id)
        return []

    rule = rules[0]
    pre_buffer = rule.buffer_minutes.pre
    post_buffer = rule.buffer_minutes.post

    if pre_buffer == 0 and post_buffer == 0:
        log.info("BUFFER: no buffer configured for provider %s", provider_id)
        return []

    provider_name = resolve_provider_name(provider_id)
    title = _buffer_title(appointment_id)

    effects: list[Effect] = []

    # 1. Delete THIS appointment's existing buffer events (at most a couple).
    delete_count = 0
    for cal in get_admin_calendars(provider_id, provider_name):
        for evt in EventModel.objects.filter(
            calendar__id=cal.id, title=title, is_cancelled=False
        ):
            effects.append(EventEffect(event_id=str(evt.id)).delete())
            delete_count += 1

    # 2. On cancel, removing the buffers is all that's needed.
    if action == "canceled":
        log.info(
            "BUFFER: canceled appt %s for provider %s — deleted %d buffer events",
            appointment_id, provider_id, delete_count,
        )
        return effects

    # 3. Don't (re)create buffers for a cancelled or past appointment.
    now = datetime.now(UTC)
    apt_start = appt.start_time
    apt_start_cmp = apt_start if apt_start.tzinfo is not None else apt_start.replace(tzinfo=UTC)
    if getattr(appt, "status", None) == "cancelled" or apt_start_cmp < now:
        log.info(
            "BUFFER: %s appt %s not active/future — deleted %d, created 0",
            action, appointment_id, delete_count,
        )
        return effects

    # 4. Create this appointment's pre/post buffers.
    calendar_id, cal_effects = get_admin_calendar_id(provider_id, provider_name=provider_name)
    if not calendar_id:
        log.warning("BUFFER: could not resolve Admin calendar for provider %s", provider_id)
        return effects
    effects.extend(cal_effects)

    apt_end = apt_start + timedelta(minutes=appt.duration_minutes)
    create_count = 0
    if pre_buffer > 0:
        effects.append(
            EventEffect(
                calendar_id=calendar_id,
                title=title,
                starts_at=apt_start - timedelta(minutes=pre_buffer),
                ends_at=apt_start,
            ).create()
        )
        create_count += 1

    if post_buffer > 0:
        effects.append(
            EventEffect(
                calendar_id=calendar_id,
                title=title,
                starts_at=apt_end,
                ends_at=apt_end + timedelta(minutes=post_buffer),
            ).create()
        )
        create_count += 1

    log.info(
        "BUFFER: %s appt %s for provider %s — deleted %d, created %d buffer events",
        action, appointment_id, provider_id, delete_count, create_count,
    )
    return effects
