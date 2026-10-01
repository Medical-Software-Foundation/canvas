"""Maintain "Buffer" calendar events around a provider's appointments.

Buffer events are the visible representation of a provider's pre/post
appointment padding, drawn on their Administrative calendar.

Clinic calendars = open availability (provider IS available).
Administrative calendars = calendar blocks (provider is NOT available).

Titles stay plain ("Buffer") so nothing technical appears on a provider's
calendar. An appointment's own buffers are located by position rather than by
an id encoded in the title: the pre-buffer is the Buffer event that ENDS when
the appointment starts, and the post-buffer is the one that STARTS when it
ends. Position does not depend on the configured buffer length, so changing
that setting never orphans an event.

Reschedules are handled explicitly rather than by rebuilding every buffer the
provider has. Canvas does not move an appointment when it is rescheduled, it
creates a new one with a new id, so the link between the two is followed to
clear the previous appointment's buffers before the replacements are drawn.
Skipping that step orphans the old buffers, and because the slot calculator
counts Administrative calendar events as busy, an orphan permanently removes
bookable time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event as EventEffect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.calendar import Event as EventModel
from logger import log

from provider_availability.engine.admin_calendar import (
    get_admin_calendar_id,
    get_admin_calendars,
    resolve_provider_name,
)
from provider_availability.engine.event_sync import DEFAULT_HORIZON_YEARS
from provider_availability.engine.models import (
    DAYS_OF_WEEK,
    ProviderAvailabilityRule,
    TimeWindow,
    date_in_pattern,
)
from provider_availability.engine.storage import get_rules_for_provider
from provider_availability.engine.tz_utils import to_provider_naive

BUFFER_TITLE = "Buffer"


def _buffer_horizon(now: datetime) -> datetime:
    """The furthest future point we create buffers for, matching availability sync."""
    try:
        return now.replace(year=now.year + DEFAULT_HORIZON_YEARS)
    except ValueError:
        # Feb 29 in a leap year — fall back to Feb 28
        return now.replace(year=now.year + DEFAULT_HORIZON_YEARS, day=now.day - 1)


class OnAppointmentCreated(BaseProtocol):
    """Draw buffer events when an appointment is booked."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        return _on_appointment_created(self.event.target.id)


class OnAppointmentRescheduled(BaseProtocol):
    """Move buffer events when an appointment is rescheduled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_RESCHEDULED)

    def compute(self) -> list[Effect]:
        return _on_appointment_rescheduled(self.event.target.id)


class OnAppointmentCanceled(BaseProtocol):
    """Remove buffer events when an appointment is canceled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        return _on_appointment_canceled(self.event.target.id)


def _load_appointment(appointment_id: str) -> Appointment | None:
    """Fetch an appointment, skipping records staff marked entered-in-error.

    A retracted appointment never should have existed, so it gets no buffers.
    """
    appt = (
        Appointment.objects.filter(id=appointment_id, entered_in_error__isnull=True)
        .select_related("provider", "location", "appointment_rescheduled_from__provider")
        .first()
    )
    if appt is None:
        log.info("BUFFER: appointment %s not found or entered in error", appointment_id)
    return appt


def _to_utc(value: datetime) -> datetime:
    """Treat a naive datetime as UTC so comparisons never raise."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _appointment_window(appt: Appointment) -> tuple[datetime, datetime]:
    """Return the appointment's (start, end)."""
    start = appt.start_time
    return start, start + timedelta(minutes=appt.duration_minutes)


def _windows_on(rule: ProviderAvailabilityRule, day: date) -> list[TimeWindow]:
    """The rule's time windows on a given date."""
    if rule.recurrence_frequency == "daily":
        return rule.time_windows
    return rule.weekly_schedule.get(DAYS_OF_WEEK[day.weekday()], [])


def _covering_rules(
    appt: Appointment, provider_id: str
) -> list[ProviderAvailabilityRule]:
    """The provider's rules that actually govern this appointment.

    Matched the way slot calculation already decides which rule produced a
    slot: the rule must be active, the appointment's local date must fall
    inside both its effective range and its recurrence pattern, its start must
    sit within one of that day's time windows, and its location must be
    permitted. Times are compared in the provider's timezone, since a rule's
    windows are written in local time while an appointment is stored in UTC.

    Visit type is deliberately not matched. A rule stores visit types as UUID
    strings while an appointment carries an integer ``note_type_id``, so
    comparing the two would match nothing rather than narrowing correctly.
    """
    local_start = to_provider_naive(appt.start_time, provider_id)
    local_date = local_start.date()
    local_time = local_start.time()
    appt_location = str(appt.location.id) if appt.location else ""

    covering: list[ProviderAvailabilityRule] = []
    for rule in get_rules_for_provider(provider_id):
        if not rule.is_active:
            continue
        if rule.effective_start and local_date < rule.effective_start:
            continue
        if rule.effective_end and local_date > rule.effective_end:
            continue
        if not date_in_pattern(
            local_date,
            rule.effective_start,
            rule.recurrence_frequency,
            rule.recurrence_interval,
            rule.weekly_schedule,
        ):
            continue
        if rule.location_ids and appt_location not in rule.location_ids:
            continue
        if not any(
            w.start <= local_time < w.end for w in _windows_on(rule, local_date)
        ):
            continue
        covering.append(rule)
    return covering


def _buffer_minutes(appt: Appointment, provider_id: str) -> tuple[int, int]:
    """The (pre, post) buffer minutes for this appointment's own rule.

    Padding follows the rule covering where the appointment actually sits, so
    rescheduling onto a day whose rule sets no padding correctly leaves it with
    none, and moving it back restores it. Reading whichever rule came first
    instead gave every one of a provider's appointments the same padding, which
    was zero whenever the first rule happened to have none configured.

    Where several rules cover one slot the largest values win, which is at
    least deterministic. Where no rule covers the appointment there is no
    configured padding to apply.
    """
    covering = _covering_rules(appt, provider_id)
    if not covering:
        log.info("BUFFER: no rule covers appt %s, drawing no padding", appt.id)
        return 0, 0
    return (
        max(r.buffer_minutes.pre for r in covering),
        max(r.buffer_minutes.post for r in covering),
    )


def _delete_buffer_effects(appt: Appointment) -> list[Effect]:
    """Delete the buffer events belonging to this one appointment.

    Located by position: a pre-buffer ends when the appointment starts, a
    post-buffer starts when it ends. Matched with ``title__startswith`` rather
    than an exact title so legacy "Buffer:<appointment id>" events from an
    earlier build are cleaned up too, with the position constraint keeping the
    match narrow.
    """
    if not appt.provider:
        return []

    provider_id = str(appt.provider.id)
    calendar_ids = [
        cal.id
        for cal in get_admin_calendars(provider_id, resolve_provider_name(provider_id))
    ]
    if not calendar_ids:
        return []

    start, end = _appointment_window(appt)
    on_admin_calendars = EventModel.objects.filter(
        calendar__id__in=calendar_ids,
        title__startswith=BUFFER_TITLE,
        is_cancelled=False,
    )
    matches = list(on_admin_calendars.filter(ends_at=start)) + list(
        on_admin_calendars.filter(starts_at=end)
    )
    return [EventEffect(event_id=str(evt.id)).delete() for evt in matches]


def _create_buffer_effects(appt: Appointment) -> list[Effect]:
    """Draw the pre/post buffer events for this one appointment."""
    if not appt.provider or appt.status == AppointmentProgressStatus.CANCELLED:
        return []
    if appt.patient_id is None:
        # Lunch, meetings and other schedule events are stored as appointments
        # with no patient. They are not visits, so they are never padded.
        return []

    provider_id = str(appt.provider.id)
    pre_buffer, post_buffer = _buffer_minutes(appt, provider_id)
    if pre_buffer == 0 and post_buffer == 0:
        return []

    start, end = _appointment_window(appt)
    now = datetime.now(UTC)
    if _to_utc(start) < now:
        # A past appointment needs no buffers drawn.
        return []
    if _to_utc(start) > _buffer_horizon(now):
        # Same ceiling the availability sync uses, so a far-future booking
        # cannot draw buffers beyond the window anything else is built for.
        return []

    calendar_id, calendar_effects = get_admin_calendar_id(
        provider_id, provider_name=resolve_provider_name(provider_id)
    )
    if not calendar_id:
        log.warning("BUFFER: could not resolve Admin calendar for provider %s", provider_id)
        return []

    effects = list(calendar_effects)
    if pre_buffer > 0:
        effects.append(
            EventEffect(
                calendar_id=calendar_id,
                title=BUFFER_TITLE,
                starts_at=start - timedelta(minutes=pre_buffer),
                ends_at=start,
            ).create()
        )
    if post_buffer > 0:
        effects.append(
            EventEffect(
                calendar_id=calendar_id,
                title=BUFFER_TITLE,
                starts_at=end,
                ends_at=end + timedelta(minutes=post_buffer),
            ).create()
        )
    return effects


def _on_appointment_created(appointment_id: str) -> list[Effect]:
    """Draw buffers for a newly booked appointment.

    Canvas fires APPOINTMENT_CREATED alongside APPOINTMENT_RESCHEDULED for the
    replacement appointment, so a reschedule reaches both handlers roughly 70ms
    apart. Each one drawing produced two sets of buffers at every time.

    Ownership is therefore decided by whether the appointment replaces another:
    a replacement belongs to the reschedule handler, which has to clear the
    predecessor's buffers anyway, and a plain booking belongs here. Having both
    handlers delete-then-create instead would race, because effects apply
    asynchronously and the second handler can query before the first one's
    events exist.
    """
    appt = _load_appointment(appointment_id)
    if appt is None:
        return []

    if appt.appointment_rescheduled_from is not None:
        log.info(
            "BUFFER: appt %s replaces another, leaving buffers to the reschedule handler",
            appointment_id,
        )
        return []

    effects = _create_buffer_effects(appt)
    log.info("BUFFER: created appt %s, %d effects", appointment_id, len(effects))
    return effects


def _on_appointment_canceled(appointment_id: str) -> list[Effect]:
    """Remove the cancelled appointment's own buffers and nothing else."""
    appt = _load_appointment(appointment_id)
    if appt is None:
        return []

    effects = _delete_buffer_effects(appt)
    log.info("BUFFER: canceled appt %s, %d buffers removed", appointment_id, len(effects))
    return effects


def _on_appointment_rescheduled(appointment_id: str) -> list[Effect]:
    """Clear the previous appointment's buffers, then draw the new ones.

    Which side of the move the event carries is not documented, so both are
    handled: ``appointment_rescheduled_from`` points back from the replacement,
    and a reverse lookup finds the replacement from the original.
    """
    appt = _load_appointment(appointment_id)
    if appt is None:
        return []

    previous = appt.appointment_rescheduled_from
    if previous is not None:
        effects = _delete_buffer_effects(previous)
        effects.extend(_create_buffer_effects(appt))
        log.info(
            "BUFFER: rescheduled appt %s replaces %s, %d effects",
            appointment_id, previous.id, len(effects),
        )
        return effects

    effects = _delete_buffer_effects(appt)
    replacement = (
        Appointment.objects.filter(
            appointment_rescheduled_from__id=appt.id, entered_in_error__isnull=True
        )
        .select_related("provider", "location")
        .first()
    )
    if replacement is not None:
        effects.extend(_create_buffer_effects(replacement))
    log.info(
        "BUFFER: rescheduled appt %s, replacement=%s, %d effects",
        appointment_id, replacement.id if replacement else None, len(effects),
    )
    return effects
