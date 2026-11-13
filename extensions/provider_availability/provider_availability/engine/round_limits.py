"""Facility round visits: the facility label, and blocking a round once it reaches its limit.

A visit booked inside a round's hours gets the facility as an appointment label,
so the facility stays visible on the schedule. When a round has a visit limit and
that many visits are booked in one occurrence, a "Round full" event on the
provider's Administrative calendar covers the occurrence, and Canvas offers no
more of its time. Cancelling, rescheduling, or restoring a visit recounts the
occurrence and adds or removes that event.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event as EventEffect
from canvas_sdk.effects.note import AddAppointmentLabel
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.calendar import Event as EventModel
from canvas_sdk.v1.data.note import NoteTypeCategories
from django.db.models.query import QuerySet
from logger import log

from provider_availability.engine.admin_calendar import (
    get_admin_calendar_id,
    get_admin_calendars,
    resolve_provider_name,
)
from provider_availability.engine.event_sync import ROUND_FULL_TITLE
from provider_availability.engine.models import DAYS_OF_WEEK, ProviderAvailabilityRule, TimeWindow, date_in_pattern
from provider_availability.engine.settings import applied_overrides, rounds_drawn
from provider_availability.engine.storage import get_rules_for_provider
from provider_availability.engine.tz_utils import localize_naive, provider_tz, to_utc

MAX_LABELS = 3  # Canvas allows three labels on an appointment
# How far ahead a whole-provider refresh recounts rounds.
REFRESH_DAYS = 120


def _windows_on(rule: ProviderAvailabilityRule, day: date) -> list[TimeWindow]:
    """A round's time windows on a date, honoring date overrides."""
    override = next((o for o in applied_overrides(rule) if o.date == day), None)
    if override is not None:
        return [] if override.is_closed else list(override.time_windows)
    if rule.effective_start and day < rule.effective_start:
        return []
    if rule.effective_end and day > rule.effective_end:
        return []
    if not date_in_pattern(day, rule.effective_start, rule.recurrence_frequency, rule.recurrence_interval, rule.weekly_schedule):
        return []
    if rule.recurrence_frequency == "daily":
        return list(rule.time_windows)
    return list(rule.weekly_schedule.get(DAYS_OF_WEEK[day.weekday()], []))


def _occurrence_utc(day: date, window: TimeWindow, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = to_utc(localize_naive(datetime.combine(day, window.start), tz))
    end = to_utc(localize_naive(datetime.combine(day, window.end), tz))
    return start, end


def round_at(
    provider_id: str,
    when: datetime,
    rules: list[ProviderAvailabilityRule] | None = None,
    tz: ZoneInfo | None = None,
) -> tuple[ProviderAvailabilityRule, datetime, datetime] | None:
    """The facility round a provider has at ``when``, with that occurrence's start and end in UTC.

    None when rounds are switched off and removed, or when no active round covers the time.
    ``rules`` and ``tz`` let a caller checking many visits read them once.
    """
    if rules is None:
        if not rounds_drawn():
            return None
        rules = get_rules_for_provider(provider_id)
    tz = tz or provider_tz(provider_id)
    local = when.astimezone(tz).replace(tzinfo=None) if when.tzinfo else when
    for rule in rules:
        if not rule.is_round or not rule.is_active:
            continue
        for window in _windows_on(rule, local.date()):
            if window.start <= local.time() < window.end:
                start, end = _occurrence_utc(local.date(), window, tz)
                return rule, start, end
    return None


def _visits_qs(provider_id: str, start: datetime, end: datetime) -> QuerySet[Appointment]:
    """Patient visits that hold a place in a round occurrence.

    Cancelled visits, entered-in-error records, and other events (lunch, meetings)
    don't count, and neither does a visit that was rescheduled to another time or
    provider, since its replacement is counted wherever it landed.
    """
    # Keyed on the original's provider: a replacement can be with someone else.
    moved_away = Appointment.objects.filter(
        appointment_rescheduled_from__provider__id=provider_id
    ).values_list("appointment_rescheduled_from__id", flat=True)
    visits: QuerySet[Appointment] = (
        Appointment.objects.filter(
            provider__id=provider_id,
            patient__isnull=False,
            entered_in_error__isnull=True,
            start_time__gte=start,
            start_time__lt=end,
        )
        .exclude(status=AppointmentProgressStatus.CANCELLED)
        .exclude(note_type__category=NoteTypeCategories.SCHEDULE_EVENT)
        .exclude(id__in=moved_away)
    )
    return visits


def visits_in(provider_id: str, start: datetime, end: datetime) -> int:
    return _visits_qs(provider_id, start, end).count()


def _full_events(
    provider_id: str, start: datetime | None = None, end: datetime | None = None, provider_name: str | None = None
) -> list[EventModel]:
    name = provider_name if provider_name is not None else resolve_provider_name(provider_id)
    cal_ids = [c.id for c in get_admin_calendars(provider_id, name)]
    if not cal_ids:
        return []
    events = EventModel.objects.filter(calendar__id__in=cal_ids, title=ROUND_FULL_TITLE, is_cancelled=False)
    if start is not None and end is not None:
        events = events.filter(starts_at=start, ends_at=end)
    else:
        events = events.filter(ends_at__gt=datetime.now(UTC))
    return list(events)


def full_block_effects(provider_id: str, rule: ProviderAvailabilityRule, start: datetime, end: datetime) -> list[Effect]:
    """Add or remove the occurrence's "Round full" event so it matches the visit count."""
    provider_name = resolve_provider_name(provider_id)
    existing = _full_events(provider_id, start, end, provider_name=provider_name)
    full = rule.max_visits is not None and visits_in(provider_id, start, end) >= rule.max_visits
    if full and not existing and end > datetime.now(UTC):
        calendar_id, calendar_effects = get_admin_calendar_id(provider_id, provider_name=provider_name)
        if not calendar_id:
            log.warning("ROUND: no Admin calendar for provider %s, can't block a full round", provider_id)
            return []
        log.info("ROUND: %s is full (%s visits) at %s, blocking it", rule.facility_name, rule.max_visits, start)
        return [*calendar_effects, EventEffect(calendar_id=calendar_id, title=ROUND_FULL_TITLE, starts_at=start, ends_at=end).create()]
    if not full and existing:
        log.info("ROUND: %s has room again at %s, unblocking it", rule.facility_name, start)
        return [EventEffect(event_id=str(evt.id)).delete() for evt in existing]
    if full and len(existing) > 1:
        # Two visit events handled at once can each add one; keep the first.
        return [EventEffect(event_id=str(evt.id)).delete() for evt in existing[1:]]
    return []


def label_effects(appt: Appointment, rule: ProviderAvailabilityRule) -> list[Effect]:
    """Label a visit booked in a round with the facility, when it has room for another label."""
    name = rule.facility_name
    if not name or appt.patient_id is None:
        return []
    have = list(appt.labels.values_list("name", flat=True))
    if name in have or len(have) >= MAX_LABELS:
        return []
    return [AddAppointmentLabel(appointment_id=str(appt.id), labels={name}).apply()]


def visit_effects(
    appt: Appointment, label: bool = True, counted: set[tuple[str, datetime, datetime]] | None = None
) -> list[Effect]:
    """Label the visit and recount its round, if it sits in one.

    ``counted`` holds the round occurrences already recounted by this handler, so a
    visit moved within one occurrence is recounted once and blocked at most once.
    """
    if appt.provider is None or appt.start_time is None:
        return []
    provider_id = str(appt.provider.id)
    found = round_at(provider_id, appt.start_time)
    if found is None:
        return []
    rule, start, end = found
    effects = label_effects(appt, rule) if label and appt.status != AppointmentProgressStatus.CANCELLED else []
    if counted is not None:
        if (provider_id, start, end) in counted:
            return effects
        counted.add((provider_id, start, end))
    effects.extend(full_block_effects(provider_id, rule, start, end))
    return effects


def refresh_provider(provider_id: str, now: datetime | None = None) -> list[Effect]:
    """Rebuild a provider's "Round full" events after their rounds change.

    Every future "Round full" event is removed, then each round occurrence in the
    next REFRESH_DAYS that is at its limit gets one again. One query reads the
    booked visits, and they are counted per occurrence here, so the work follows
    the bookings rather than the length of the horizon.
    """
    now = now or datetime.now(UTC)
    provider_name = resolve_provider_name(provider_id)
    effects: list[Effect] = [
        EventEffect(event_id=str(evt.id)).delete() for evt in _full_events(provider_id, provider_name=provider_name)
    ]
    rounds = [r for r in get_rules_for_provider(provider_id) if r.is_round and r.is_active and r.max_visits]
    if not rounds or not rounds_drawn():
        return effects
    tz = provider_tz(provider_id)
    # A day back, so a round in progress counts the visits already behind it.
    starts = _visits_qs(provider_id, now - timedelta(days=1), now + timedelta(days=REFRESH_DAYS)).values_list(
        "start_time", flat=True
    )
    counts: dict[tuple[datetime, datetime], int] = {}
    limits: dict[tuple[datetime, datetime], int] = {}
    for start_time in starts:
        found = round_at(provider_id, start_time, rules=rounds, tz=tz)
        if found is None:
            continue
        rule, start, end = found
        counts[(start, end)] = counts.get((start, end), 0) + 1
        limits[(start, end)] = rule.max_visits or 0
    full = sorted(key for key, n in counts.items() if key[1] > now and n >= limits[key])
    if not full:
        return effects
    calendar_id, calendar_effects = get_admin_calendar_id(provider_id, provider_name=provider_name)
    if not calendar_id:
        log.warning("ROUND: no Admin calendar for provider %s, can't block full rounds", provider_id)
        return effects
    effects.extend(calendar_effects)
    for start, end in full:
        effects.append(EventEffect(calendar_id=calendar_id, title=ROUND_FULL_TITLE, starts_at=start, ends_at=end).create())
    return effects
