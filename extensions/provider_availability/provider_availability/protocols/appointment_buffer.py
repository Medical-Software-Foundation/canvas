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

from provider_availability.engine.admin_calendar import get_admin_calendar_id, get_admin_calendars
from provider_availability.engine.storage import get_rules_for_provider

BUFFER_TITLE = "Buffer"


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
    """Delete all Buffer events for this provider, then recreate for active appointments."""
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

    # Get or create the Administrative calendar
    calendar_id, cal_effects = get_admin_calendar_id(provider_id)
    if not calendar_id:
        log.warning("BUFFER: could not resolve Admin calendar for provider %s", provider_id)
        return []

    effects: list[Effect] = list(cal_effects)

    # 1. Delete ALL existing Buffer events on the admin calendar
    delete_count = 0
    for cal in get_admin_calendars(provider_id):
        for evt in EventModel.objects.filter(
            calendar__id=cal.id, title=BUFFER_TITLE, is_cancelled=False
        ):
            effects.append(EventEffect(event_id=str(evt.id)).delete())
            delete_count += 1

    # 2. Query all future non-canceled appointments for this provider
    now = datetime.now(UTC)
    appointments = Appointment.objects.filter(
        provider__id=provider_id,
        start_time__gte=now,
    ).exclude(status="cancelled")

    # 3. Create buffer events for each active appointment
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
        "BUFFER: %s appt %s for provider %s — deleted %d, created %d buffer events",
        action, appointment_id, provider_id, delete_count, create_count,
    )
    return effects
