"""Sync layer: convert availability rules into Canvas Calendar + Event effects."""

from __future__ import annotations

import datetime as dt
from datetime import UTC, date, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Calendar as CalendarEffect
from canvas_sdk.effects.calendar import CalendarType
from canvas_sdk.effects.calendar import DaysOfWeek, Event as EventEffect, EventRecurrence
from canvas_sdk.v1.data import PracticeLocation
from canvas_sdk.v1.data.calendar import Calendar as CalendarModel
from canvas_sdk.v1.data.calendar import Event as EventModel
from canvas_sdk.v1.data.staff import Staff
from logger import log

from zoneinfo import ZoneInfo

from provider_availability.engine.admin_calendar import (
    deterministic_calendar_id,
    get_admin_calendar_id,
    get_admin_calendars,
)
from provider_availability.engine.models import (
    AdminBlock,
    DateOverride,
    ProviderAvailabilityRule,
    RecurringBlock,
    date_in_pattern,
)
from provider_availability.engine.storage import get_event_ids, get_rules_for_provider
from provider_availability.engine.tz_utils import localize_naive, provider_tz, to_utc

DAY_TO_WEEKDAY: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

DAY_TO_DAYS_OF_WEEK: dict[str, DaysOfWeek] = {
    "monday": DaysOfWeek.Monday,
    "tuesday": DaysOfWeek.Tuesday,
    "wednesday": DaysOfWeek.Wednesday,
    "thursday": DaysOfWeek.Thursday,
    "friday": DaysOfWeek.Friday,
    "saturday": DaysOfWeek.Saturday,
    "sunday": DaysOfWeek.Sunday,
}

AVAILABILITY_TITLE = "Available"
BLOCK_TITLE = "Block"
LEAD_TIME_TITLE = "Lead Time"
RECURRING_BLOCK_TITLE = "Recurring Block"
# Transitional: kept for one deploy to clean up existing Override Block events
OVERRIDE_BLOCK_TITLE = "Override Block"

# How far ahead to create events when no effective_end is set
DEFAULT_HORIZON_YEARS = 25

# Rolling window for hold-type admin block generation
HOLD_BLOCK_WINDOW_DAYS = 30
HOLD_BLOCK_TITLE = "Hold Block"  # legacy prefix, kept for cleanup queries
HOLD_TITLE_PREFIXES = ["Hold Block", "Same Day Hold", "Next Day Hold", "Same-Day Hold", "Next-Day Hold"]

# Only rebuild lead-time blocks when boundaries have drifted beyond this threshold
LEAD_TIME_DRIFT_THRESHOLD_SECONDS = 300  # 5 minutes


def sync_provider_availability(provider_id: str) -> list[Effect]:
    """Delete all availability events and recreate for ALL active rules.

    This is the correct entry point for syncing availability. It handles
    multiple rules per provider without accidentally deleting sibling rules.
    """
    effects: list[Effect] = []
    effects.extend(build_delete_effects(provider_id))

    rules = get_rules_for_provider(provider_id)
    total_events = 0
    for rule in rules:
        has_schedule = (
            rule.weekly_schedule
            if rule.recurrence_frequency != "daily"
            else bool(rule.time_windows)
        )
        if rule.is_active and has_schedule:
            rule_effects = _build_rule_events(rule)
            effects.extend(rule_effects)
            total_events += len(rule_effects)

    log.info(
        "sync_provider_availability: provider=%s, %d rules, %d event effects",
        provider_id, len(rules), total_events,
    )
    return effects


def build_sync_effects(rule: ProviderAvailabilityRule) -> list[Effect]:
    """Build Calendar + Event effects to sync a single rule.

    WARNING: This deletes ALL availability events for the provider, then
    recreates only for the given rule. Use sync_provider_availability()
    when the provider has multiple rules.
    """
    effects: list[Effect] = []
    effects.extend(build_delete_effects(rule.provider_id))
    effects.extend(_build_rule_events(rule))
    return effects


def _build_rule_events(rule: ProviderAvailabilityRule) -> list[Effect]:
    """Create Calendar + Event effects for a single rule (no deletion).

    Creates a Clinic calendar per provider+location (if needed) and
    recurring Events (Weekly or Daily, with custom interval) that Canvas
    uses for native slot generation.
    """
    effects: list[Effect] = []

    is_daily = rule.recurrence_frequency == "daily"
    if is_daily:
        if not rule.time_windows:
            return effects
    else:
        if not rule.weekly_schedule:
            return effects

    # If no locations specified, create events for ALL active locations
    if rule.location_ids:
        location_ids: list[str] = list(rule.location_ids)
    else:
        location_ids = [
            str(loc.id) for loc in PracticeLocation.objects.filter(active=True)
        ]
        log.info(
            "_build_rule_events: rule=%s has no locations, using all %d active locations",
            rule.id, len(location_ids),
        )
        if not location_ids:
            log.warning("_build_rule_events: no active locations found, skipping event creation")
            return effects

    # Determine the date range
    today = date.today()
    range_start = rule.effective_start if rule.effective_start and rule.effective_start > today else today
    if rule.effective_end:
        range_end = rule.effective_end
    else:
        try:
            range_end = today.replace(year=today.year + DEFAULT_HORIZON_YEARS)
        except ValueError:
            # Feb 29 in a leap year — fall back to Feb 28
            range_end = today.replace(year=today.year + DEFAULT_HORIZON_YEARS, day=today.day - 1)

    # Use None for allowed_note_types when no restriction (= all types allowed).
    # An empty list [] means "no types allowed" in Canvas, which blocks all bookings.
    note_types: list[str] | None = list(rule.visit_types) if rule.visit_types else None

    tz = ZoneInfo(rule.timezone) if rule.timezone else provider_tz(rule.provider_id)
    interval = max(1, rule.recurrence_interval)
    event_count = 0

    for location_id in location_ids:
        calendar_id, cal_effects = _get_calendar_id(rule.provider_id, location_id)
        effects.extend(cal_effects)

        if is_daily:
            # Daily: emit one recurring event per time_window covering the full range.
            # Daily anchor is the first in-pattern date >= range_start.
            anchor = rule.effective_start or range_start
            if anchor < range_start:
                # advance to first in-pattern date >= range_start
                offset = (range_start - anchor).days
                if offset % interval != 0:
                    anchor = range_start + dt.timedelta(days=interval - (offset % interval))
                else:
                    anchor = range_start
            if anchor > range_end:
                continue

            for window in rule.time_windows:
                starts_at = to_utc(localize_naive(datetime.combine(anchor, window.start), tz))
                ends_at = to_utc(localize_naive(datetime.combine(anchor, window.end), tz))
                recurrence_ends = to_utc(localize_naive(datetime.combine(range_end, window.end), tz))
                event = EventEffect(
                    calendar_id=calendar_id,
                    title=AVAILABILITY_TITLE,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    recurrence_frequency=EventRecurrence.Daily,
                    recurrence_interval=interval,
                    recurrence_ends_at=recurrence_ends,
                    allowed_note_types=note_types,
                ).create()
                effects.append(event)
                event_count += 1

            # Daily mode: still honor explicit date_overrides by emitting one-off events.
            for ovr in rule.date_overrides:
                if ovr.is_closed or not ovr.time_windows:
                    continue
                for ovr_window in ovr.time_windows:
                    starts_at = to_utc(localize_naive(datetime.combine(ovr.date, ovr_window.start), tz))
                    ends_at = to_utc(localize_naive(datetime.combine(ovr.date, ovr_window.end), tz))
                    event = EventEffect(
                        calendar_id=calendar_id,
                        title=AVAILABILITY_TITLE,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        allowed_note_types=note_types,
                    ).create()
                    effects.append(event)
                    event_count += 1
            continue

        # Weekly path
        # Collect override dates by weekday for splitting recurring events
        overrides_by_weekday: dict[int, list[DateOverride]] = {}
        if rule.date_overrides:
            for ovr in rule.date_overrides:
                overrides_by_weekday.setdefault(ovr.date.weekday(), []).append(ovr)

        for day, windows in rule.weekly_schedule.items():
            weekday_int = DAY_TO_WEEKDAY.get(day)
            dow = DAY_TO_DAYS_OF_WEEK.get(day)
            if weekday_int is None or dow is None:
                continue

            # Find first occurrence of this weekday in the range
            first_date = _next_weekday(range_start, weekday_int)
            if first_date > range_end:
                continue

            # Get override dates for this weekday (within range)
            day_overrides = [
                ovr for ovr in overrides_by_weekday.get(weekday_int, [])
                if first_date <= ovr.date <= range_end
            ]
            override_dates = sorted(ovr.date for ovr in day_overrides)
            step_days = 7 * interval

            for window in windows:
                if not override_dates:
                    # No overrides — single recurring event
                    starts_at = to_utc(localize_naive(datetime.combine(first_date, window.start), tz))
                    ends_at = to_utc(localize_naive(datetime.combine(first_date, window.end), tz))
                    recurrence_ends = to_utc(localize_naive(datetime.combine(range_end, window.end), tz))

                    event = EventEffect(
                        calendar_id=calendar_id,
                        title=AVAILABILITY_TITLE,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        recurrence_frequency=EventRecurrence.Weekly,
                        recurrence_interval=interval,
                        recurrence_days=[dow],
                        recurrence_ends_at=recurrence_ends,
                        allowed_note_types=note_types,
                    ).create()
                    effects.append(event)
                    event_count += 1
                else:
                    # Split recurring event into segments that skip override dates
                    segments = _compute_recurring_segments(
                        first_date, range_end, override_dates, step_days=step_days,
                    )
                    for seg_start, seg_end in segments:
                        starts_at = to_utc(localize_naive(datetime.combine(seg_start, window.start), tz))
                        ends_at = to_utc(localize_naive(datetime.combine(seg_start, window.end), tz))
                        recurrence_ends = to_utc(localize_naive(datetime.combine(seg_end, window.end), tz))

                        event = EventEffect(
                            calendar_id=calendar_id,
                            title=AVAILABILITY_TITLE,
                            starts_at=starts_at,
                            ends_at=ends_at,
                            recurrence_frequency=EventRecurrence.Weekly,
                            recurrence_interval=interval,
                            recurrence_days=[dow],
                            recurrence_ends_at=recurrence_ends,
                            allowed_note_types=note_types,
                        ).create()
                        effects.append(event)
                        event_count += 1

            # Create one-off Clinic events for each override's time_windows
            for ovr in day_overrides:
                if ovr.is_closed or not ovr.time_windows:
                    continue
                for ovr_window in ovr.time_windows:
                    starts_at = to_utc(localize_naive(datetime.combine(ovr.date, ovr_window.start), tz))
                    ends_at = to_utc(localize_naive(datetime.combine(ovr.date, ovr_window.end), tz))
                    event = EventEffect(
                        calendar_id=calendar_id,
                        title=AVAILABILITY_TITLE,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        allowed_note_types=note_types,
                    ).create()
                    effects.append(event)
                    event_count += 1

    log.info(
        "_build_rule_events: rule=%s freq=%s interval=%s range=%s..%s events=%d",
        rule.id, rule.recurrence_frequency, interval, range_start, range_end, event_count,
    )
    return effects


def _compute_recurring_segments(
    first_date: date,
    range_end: date,
    override_dates: list[date],
    step_days: int = 7,
) -> list[tuple[date, date]]:
    """Split a recurring range into segments that skip override dates.

    Each segment is a (start_date, end_date) pair representing consecutive
    in-pattern occurrences spaced `step_days` apart. Override dates that
    don't fall on an in-pattern occurrence are ignored (they're already
    skipped by the recurrence). For overrides that do fall on the pattern,
    the segment before ends `step_days` prior, and the segment after starts
    `step_days` later.

    step_days = 7 for weekly interval=1, 14 for bi-weekly, N for daily/N.
    """
    segments: list[tuple[date, date]] = []
    current_start = first_date
    for ovr_date in sorted(override_dates):
        if ovr_date < first_date or (ovr_date - first_date).days % step_days != 0:
            continue  # not on pattern — recurrence already skips it
        seg_end = ovr_date - dt.timedelta(days=step_days)
        if seg_end >= current_start:
            segments.append((current_start, seg_end))
        current_start = ovr_date + dt.timedelta(days=step_days)
    if current_start <= range_end:
        segments.append((current_start, range_end))
    return segments


def build_delete_effects(provider_id: str) -> list[Effect]:
    """Delete all 'Available' events on the provider's Clinic calendars.

    Queries the database for existing events rather than relying on cached IDs.
    """
    try:
        staff = Staff.objects.get(id=provider_id)
        provider_name = staff.full_name
    except Staff.DoesNotExist:
        log.warning("build_delete_effects: provider %s not found", provider_id)
        return []

    if not provider_name:
        return []

    cal_ids = [
        c.id
        for c in CalendarModel.objects.filter(
            title__startswith=provider_name + ": Clinic"
        )
    ]
    if not cal_ids:
        return []

    effects: list[Effect] = []
    now = datetime.now(UTC)
    # Single bulk query across all the provider's Clinic calendars.
    for evt in EventModel.objects.filter(
        calendar__id__in=cal_ids,
        title=AVAILABILITY_TITLE,
        is_cancelled=False,
    ):
        # Preserve fully-past events for historical reporting
        end_boundary = getattr(evt, "recurrence_ends_at", None) or evt.ends_at
        if end_boundary and end_boundary < now:
            continue
        effects.append(EventEffect(event_id=str(evt.id)).delete())

    if effects:
        log.info(
            "build_delete_effects: provider=%s, %d Clinic calendars, total %d delete effects",
            provider_id, len(cal_ids), len(effects),
        )

    return effects


def _weekday_occurrences(start: date, end: date, weekday_int: int) -> list[date]:
    """Return all occurrences of a weekday (0=Mon, 6=Sun) between start and end inclusive."""
    first = _next_weekday(start, weekday_int)
    result: list[date] = []
    current = first
    while current <= end:
        result.append(current)
        current += dt.timedelta(days=7)
    return result


def _next_weekday(from_date: date, weekday_int: int) -> date:
    """Find the next occurrence of a weekday (0=Mon, 6=Sun) on or after from_date."""
    days_ahead = weekday_int - from_date.weekday()
    if days_ahead < 0:
        days_ahead += 7
    return from_date + dt.timedelta(days=days_ahead)


def _get_calendar_id(
    provider_id: str, location_id: str | None
) -> tuple[str, list[Effect]]:
    """Get or create a Clinic calendar for a provider+location.

    Returns (calendar_id, effects_needed_to_create).
    """
    try:
        staff = Staff.objects.get(id=provider_id)
        provider_name = staff.full_name
    except Staff.DoesNotExist:
        provider_name = ""

    location_name = ""
    if location_id:
        try:
            loc = PracticeLocation.objects.get(id=location_id)
            location_name = loc.full_name
        except PracticeLocation.DoesNotExist:
            pass

    new_id = deterministic_calendar_id(provider_id, CalendarType.Clinic, location_id)
    if provider_name:
        loc_arg = location_name or None
        # Prefer the deterministic anchor id; fall back to title for legacy
        # calendars created before deterministic ids existed.
        existing = (
            CalendarModel.objects.filter(id=new_id).first()
            or CalendarModel.objects.for_calendar_name(
                provider_name=provider_name,
                calendar_type=CalendarType.Clinic,
                location=loc_arg,
            ).first()
        )
        if existing:
            log.info(
                "_get_calendar_id: found existing calendar id=%s title=%s",
                existing.id, existing.title,
            )
            return str(existing.id), []

    log.info(
        "_get_calendar_id: creating new calendar for provider=%s location=%s",
        provider_id, location_id,
    )
    cal_effect = CalendarEffect(
        id=new_id,
        provider=provider_id,
        type=CalendarType.Clinic,
        location=location_id if location_id else None,
        # Store the staff UUID in description so the calendar can be resolved
        # back to its provider even after a rename (title is name-based).
        description=str(provider_id),
    ).create()

    return new_id, [cal_effect]


# ── Admin block → Calendar Event sync ────────────────────────────────


def build_block_event_effects(block: AdminBlock) -> list[Effect]:
    """Create Administrative calendar events for a one-off admin block.

    Creates per-location Admin calendar events when the block has location_ids,
    or a single provider-level event when no locations are specified.
    """
    effects: list[Effect] = []
    title = block.reason if block.reason else "Blocked"

    # Localize to provider TZ if naive, then convert to UTC.
    tz = provider_tz(block.provider_id)
    starts_at = to_utc(block.start if block.start.tzinfo is not None else localize_naive(block.start, tz))
    ends_at = to_utc(block.end if block.end.tzinfo is not None else localize_naive(block.end, tz))

    # Determine which location calendars to create events on
    location_ids: list[str | None]
    if block.location_ids:
        location_ids = list(block.location_ids)
    else:
        location_ids = [None]  # provider-level (no location)

    for loc_id in location_ids:
        calendar_id, cal_effects = get_admin_calendar_id(block.provider_id, loc_id)
        if not calendar_id:
            log.warning("build_block_event_effects: no Admin calendar for provider %s location=%s", block.provider_id, loc_id)
            continue

        effects.extend(cal_effects)
        event = EventEffect(
            calendar_id=calendar_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
        ).create()
        effects.append(event)

    log.info(
        "build_block_event_effects: created %d block events for provider=%s locations=%s title=%s",
        len(effects), block.provider_id, block.location_ids, title,
    )
    return effects


def build_delete_block_effects(provider_id: str, block: AdminBlock | None = None) -> list[Effect]:
    """Delete admin block events from the provider's Administrative calendars.

    If a specific block is given, first try stored event IDs, then fall back to
    time-range matching (with TZ conversion). Also matches by title (reason).
    Otherwise, delete all block-titled events.
    """
    effects: list[Effect] = []

    if block:
        # Try stored event IDs first
        stored_ids = get_event_ids(block.id)
        if stored_ids:
            for eid in stored_ids:
                effects.append(EventEffect(event_id=eid).delete())
            log.info("build_delete_block_effects: block=%s, deleted %d events by stored IDs", block.id, len(effects))
            return effects

        # Fall back to time-range matching — convert block times to UTC for comparison
        tz = provider_tz(provider_id)
        block_start_utc = to_utc(block.start if block.start.tzinfo is not None else localize_naive(block.start, tz))
        block_end_utc = to_utc(block.end if block.end.tzinfo is not None else localize_naive(block.end, tz))
        block_title = block.reason if block.reason else "Blocked"

        cal_ids = [c.id for c in get_admin_calendars(provider_id)]
        if cal_ids:
            # Match by converted UTC times across all the provider's Admin calendars
            for evt in EventModel.objects.filter(
                calendar__id__in=cal_ids,
                is_cancelled=False,
                starts_at=block_start_utc,
                ends_at=block_end_utc,
            ):
                effects.append(EventEffect(event_id=str(evt.id)).delete())
            # Also match by title if time match found nothing (handles TZ edge cases)
            if not effects:
                for evt in EventModel.objects.filter(
                    calendar__id__in=cal_ids,
                    is_cancelled=False,
                    title=block_title,
                    starts_at__date=block_start_utc.date(),
                ):
                    effects.append(EventEffect(event_id=str(evt.id)).delete())
    else:
        cal_ids = [c.id for c in get_admin_calendars(provider_id)]
        if cal_ids:
            for evt in EventModel.objects.filter(
                calendar__id__in=cal_ids,
                title=BLOCK_TITLE,
                is_cancelled=False,
            ):
                effects.append(EventEffect(event_id=str(evt.id)).delete())

    if effects:
        log.info("build_delete_block_effects: provider=%s, %d delete effects", provider_id, len(effects))
    return effects


# ── Lead-time block sync ──────────────────────────────────────────────

def delete_all_lead_time_events() -> list[Effect]:
    """Delete ALL 'Lead Time' events across ALL Administrative calendars.

    Used during plugin install to clean up orphaned lead-time events
    from providers whose rules may no longer be cached.
    """
    admin_cal_ids = [
        c.id for c in CalendarModel.objects.filter(title__contains=": Admin")
    ]
    if not admin_cal_ids:
        return []
    effects: list[Effect] = [
        EventEffect(event_id=str(evt.id)).delete()
        for evt in EventModel.objects.filter(
            calendar__id__in=admin_cal_ids,
            title=LEAD_TIME_TITLE,
            is_cancelled=False,
        )
    ]

    if effects:
        log.info("delete_all_lead_time_events: deleting %d orphaned lead-time events", len(effects))
    return effects


def delete_provider_lead_time_events(provider_id: str) -> list[Effect]:
    """Delete all 'Lead Time' events on a single provider's Admin calendars.

    Used to clean up orphaned lead-time blocks when a provider has no active
    rules requiring lead time. One bulk query across all the provider's Admin
    calendars.
    """
    cal_ids = [c.id for c in get_admin_calendars(provider_id)]
    if not cal_ids:
        return []
    return [
        EventEffect(event_id=str(evt.id)).delete()
        for evt in EventModel.objects.filter(
            calendar__id__in=cal_ids,
            title=LEAD_TIME_TITLE,
            is_cancelled=False,
        )
    ]


def build_lead_time_block_effects(rule: ProviderAvailabilityRule) -> list[Effect]:
    """Create Administrative blocks within the lead-time window, but only
    during the provider's working hours.

    Instead of one big block from now to now + min_lead_hours, this
    intersects the lead-time cutoff with the provider's availability
    windows so the calendar stays clean and only bookable hours are blocked.

    Called every cron tick. Skips the rebuild if existing lead-time events
    are within LEAD_TIME_DRIFT_THRESHOLD_SECONDS of the expected window.
    """
    min_lead = rule.booking_interval.min_lead_hours
    if min_lead <= 0:
        return []

    calendar_id, cal_effects = get_admin_calendar_id(rule.provider_id)
    if not calendar_id:
        return []

    # Compute the desired window in the provider's TZ
    tz = provider_tz(rule.provider_id)
    now_local = datetime.now(tz)
    lead_end_local = now_local + dt.timedelta(hours=min_lead)

    # Build the list of (start, end) intervals where lead-time blocks are needed:
    # the intersection of [now, now+lead] with the provider's availability windows.
    lead_intervals: list[tuple[datetime, datetime]] = []
    current_date = now_local.date()
    end_date = lead_end_local.date()

    # Check date overrides — use override windows instead of weekly schedule
    override_lookup = {o.date: o for o in rule.date_overrides}

    rule_is_daily = rule.recurrence_frequency == "daily"
    rule_interval = max(1, rule.recurrence_interval)
    while current_date <= end_date:
        override = override_lookup.get(current_date)
        if override is not None:
            if override.is_closed:
                current_date += dt.timedelta(days=1)
                continue
            windows = override.time_windows
        elif not date_in_pattern(
            current_date, rule.effective_start, rule.recurrence_frequency,
            rule_interval, rule.weekly_schedule,
        ):
            current_date += dt.timedelta(days=1)
            continue
        elif rule_is_daily:
            windows = rule.time_windows
        else:
            day_name = current_date.strftime("%A").lower()
            windows = rule.weekly_schedule.get(day_name, [])
        for window in windows:
            win_start = datetime.combine(current_date, window.start).replace(tzinfo=tz)
            win_end = datetime.combine(current_date, window.end).replace(tzinfo=tz)
            # Intersect with lead-time range
            block_start = max(win_start, now_local)
            block_end = min(win_end, lead_end_local)
            if block_start < block_end:
                lead_intervals.append((block_start, block_end))
        current_date += dt.timedelta(days=1)

    if not lead_intervals:
        # No availability windows overlap with the lead-time range — still
        # need to clean up any existing lead-time events.
        pass

    # Check if existing lead-time events are still close enough to skip rebuild
    admin_cal_ids = [c.id for c in get_admin_calendars(rule.provider_id)]
    existing_events = (
        list(
            EventModel.objects.filter(
                calendar__id__in=admin_cal_ids,
                title=LEAD_TIME_TITLE,
                is_cancelled=False,
            ).order_by("starts_at")
        )
        if admin_cal_ids
        else []
    )

    if existing_events and lead_intervals:
        existing_start = existing_events[0].starts_at
        existing_end = existing_events[-1].ends_at
        if existing_start.tzinfo is None:
            existing_start = existing_start.replace(tzinfo=UTC)
        if existing_end.tzinfo is None:
            existing_end = existing_end.replace(tzinfo=UTC)
        expected_start_utc = to_utc(lead_intervals[0][0])
        expected_end_utc = to_utc(lead_intervals[-1][1])
        start_drift = abs((existing_start - expected_start_utc).total_seconds())
        end_drift = abs((existing_end - expected_end_utc).total_seconds())
        if (
            len(existing_events) == len(lead_intervals)
            and start_drift < LEAD_TIME_DRIFT_THRESHOLD_SECONDS
            and end_drift < LEAD_TIME_DRIFT_THRESHOLD_SECONDS
        ):
            return list(cal_effects)  # existing events are close enough, skip rebuild

    effects: list[Effect] = list(cal_effects)

    # Delete existing lead-time events
    for evt in existing_events:
        effects.append(EventEffect(event_id=str(evt.id)).delete())

    # Create lead-time blocks only during working hours
    for block_start, block_end in lead_intervals:
        event = EventEffect(
            calendar_id=calendar_id,
            title=LEAD_TIME_TITLE,
            starts_at=to_utc(block_start),
            ends_at=to_utc(block_end),
        ).create()
        effects.append(event)

    log.info(
        "build_lead_time_block_effects: provider=%s lead=%dh, %d blocks during working hours (%s to %s)",
        rule.provider_id, min_lead, len(lead_intervals), now_local, lead_end_local,
    )
    return effects


# ── Override-aware helpers ─────────────────────────────────────────────


def _get_provider_override_map(provider_id: str) -> dict[date, list]:
    """Get all override dates for a provider mapped to their time windows.

    Returns {override_date: [TimeWindow, ...]} for all rules of the provider.
    Used to suppress recurring blocks/holds on dates where availability is narrowed.
    """
    override_map: dict[date, list] = {}
    for rule in get_rules_for_provider(provider_id):
        for ovr in rule.date_overrides:
            if ovr.is_closed:
                override_map[ovr.date] = []  # empty = fully closed
            else:
                override_map[ovr.date] = list(ovr.time_windows)
    return override_map


def _block_outside_override(block_windows: list, override_windows: list) -> bool:
    """Return True if ALL block windows fall entirely outside override windows.

    If override_windows is empty (closed day), always returns True.
    """
    if not override_windows:
        return True  # closed day — all blocks are outside
    for bw in block_windows:
        for ow in override_windows:
            # Check if block window overlaps with override window
            if bw.start < ow.end and ow.start < bw.end:
                return False  # at least partially inside
    return True  # all block windows are outside all override windows


# ── Recurring block sync ──────────────────────────────────────────────


def build_recurring_block_sync_effects(block: RecurringBlock) -> list[Effect]:
    """Create recurring weekly Administrative events for a RecurringBlock.

    Similar pattern to build_sync_effects but creates blocking events on
    Administrative calendars instead of availability events on Clinic calendars.
    """
    effects: list[Effect] = []

    # Delete old recurring block events first
    effects.extend(build_delete_recurring_block_effects(block.provider_id, block))

    is_daily = block.recurrence_frequency == "daily"
    has_schedule = bool(block.time_windows) if is_daily else bool(block.weekly_schedule)
    if not has_schedule or not block.is_active:
        return effects

    # Hold-type blocks: generate one-off admin events for each blocked date in a rolling window
    if block.hold_type != "none":
        effects.extend(_build_hold_block_events(block))
        return effects

    today = date.today()
    range_start = block.effective_start if block.effective_start and block.effective_start > today else today

    if block.effective_end:
        range_end = block.effective_end
    else:
        try:
            range_end = today.replace(year=today.year + DEFAULT_HORIZON_YEARS)
        except ValueError:
            range_end = today.replace(year=today.year + DEFAULT_HORIZON_YEARS, day=today.day - 1)

    title = block.reason if block.reason else "Blocked"
    tz = ZoneInfo(block.timezone) if block.timezone else provider_tz(block.provider_id)
    interval = max(1, block.recurrence_interval)

    # Determine which location calendars to create events on
    if block.location_ids:
        location_ids: list[str | None] = list(block.location_ids)
    else:
        location_ids = [None]  # provider-level (no location)

    # Collect override dates where this block should be suppressed
    override_map = _get_provider_override_map(block.provider_id)

    event_count = 0
    for loc_id in location_ids:
        calendar_id, cal_effects = get_admin_calendar_id(block.provider_id, loc_id)
        if not calendar_id:
            log.warning("build_recurring_block_sync_effects: no Admin calendar for provider %s location=%s", block.provider_id, loc_id)
            continue

        effects.extend(cal_effects)

        if is_daily:
            anchor = block.effective_start or range_start
            if anchor < range_start:
                offset = (range_start - anchor).days
                if offset % interval != 0:
                    anchor = range_start + dt.timedelta(days=interval - (offset % interval))
                else:
                    anchor = range_start
            if anchor > range_end:
                continue
            for window in block.time_windows:
                starts_at = to_utc(localize_naive(datetime.combine(anchor, window.start), tz))
                ends_at = to_utc(localize_naive(datetime.combine(anchor, window.end), tz))
                recurrence_ends = to_utc(localize_naive(datetime.combine(range_end, window.end), tz))
                event = EventEffect(
                    calendar_id=calendar_id,
                    title=title,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    recurrence_frequency=EventRecurrence.Daily,
                    recurrence_interval=interval,
                    recurrence_ends_at=recurrence_ends,
                ).create()
                effects.append(event)
                event_count += 1
            continue

        # Weekly path
        step_days = 7 * interval
        for day, windows in block.weekly_schedule.items():
            weekday_int = DAY_TO_WEEKDAY.get(day)
            dow = DAY_TO_DAYS_OF_WEEK.get(day)
            if weekday_int is None or dow is None:
                continue

            first_date = _next_weekday(range_start, weekday_int)
            if first_date > range_end:
                continue

            # Find override dates on this weekday where block falls outside override window
            skip_dates = sorted(
                ovr_date for ovr_date, ovr_windows in override_map.items()
                if ovr_date.weekday() == weekday_int
                and first_date <= ovr_date <= range_end
                and _block_outside_override(windows, ovr_windows)
            )

            for window in windows:
                if not skip_dates:
                    # No overrides to skip — single recurring event
                    starts_at = to_utc(localize_naive(datetime.combine(first_date, window.start), tz))
                    ends_at = to_utc(localize_naive(datetime.combine(first_date, window.end), tz))
                    recurrence_ends = to_utc(localize_naive(datetime.combine(range_end, window.end), tz))

                    event = EventEffect(
                        calendar_id=calendar_id,
                        title=title,
                        starts_at=starts_at,
                        ends_at=ends_at,
                        recurrence_frequency=EventRecurrence.Weekly,
                        recurrence_interval=interval,
                        recurrence_days=[dow],
                        recurrence_ends_at=recurrence_ends,
                    ).create()
                    effects.append(event)
                    event_count += 1
                else:
                    # Split recurring event around override dates
                    segments = _compute_recurring_segments(
                        first_date, range_end, skip_dates, step_days=step_days,
                    )
                    for seg_start, seg_end in segments:
                        starts_at = to_utc(localize_naive(datetime.combine(seg_start, window.start), tz))
                        ends_at = to_utc(localize_naive(datetime.combine(seg_start, window.end), tz))
                        recurrence_ends = to_utc(localize_naive(datetime.combine(seg_end, window.end), tz))

                        event = EventEffect(
                            calendar_id=calendar_id,
                            title=title,
                            starts_at=starts_at,
                            ends_at=ends_at,
                            recurrence_frequency=EventRecurrence.Weekly,
                            recurrence_interval=interval,
                            recurrence_days=[dow],
                            recurrence_ends_at=recurrence_ends,
                        ).create()
                        effects.append(event)
                        event_count += 1

    log.info(
        "build_recurring_block_sync_effects: provider=%s freq=%s interval=%s events=%d range=%s..%s locations=%s",
        block.provider_id, block.recurrence_frequency, interval, event_count, range_start, range_end, block.location_ids,
    )
    return effects


def _build_hold_block_events(block: RecurringBlock) -> list[Effect]:
    """Generate one-off admin events for a hold-type recurring block.

    Creates individual blocking events for each future date that should be
    blocked within a rolling window (HOLD_BLOCK_WINDOW_DAYS).

    - same_day: blocks dates > today (today's slots remain available)
    - next_day: blocks dates > today + 1 (today and tomorrow available)
    """
    effects: list[Effect] = []
    today = date.today()

    # Determine the first date that should be blocked
    if block.hold_type == "same_day":
        block_after = today  # block dates > today
    elif block.hold_type == "next_day":
        block_after = today + dt.timedelta(days=1)  # block dates > today+1
    else:
        return effects

    tz = ZoneInfo(block.timezone) if block.timezone else provider_tz(block.provider_id)
    hold_type_label = "Same Day Hold" if block.hold_type == "same_day" else "Next Day Hold"
    title = hold_type_label + (": " + block.reason if block.reason else "")

    # Determine the range
    range_start = block.effective_start if block.effective_start and block.effective_start > today else today
    window_end = today + dt.timedelta(days=HOLD_BLOCK_WINDOW_DAYS)
    range_end = min(window_end, block.effective_end) if block.effective_end else window_end

    # Collect override dates to suppress holds outside override windows
    override_map = _get_provider_override_map(block.provider_id)

    # Determine which location calendars to create events on
    if block.location_ids:
        location_ids: list[str | None] = list(block.location_ids)
    else:
        location_ids = [None]  # provider-level (no location)

    event_count = 0
    for loc_id in location_ids:
        calendar_id, cal_effects = get_admin_calendar_id(block.provider_id, loc_id)
        if not calendar_id:
            log.warning("_build_hold_block_events: no Admin calendar for provider %s location=%s", block.provider_id, loc_id)
            continue

        effects.extend(cal_effects)

        is_daily = block.recurrence_frequency == "daily"
        current_date = range_start
        while current_date <= range_end:
            if current_date <= block_after:
                current_date += dt.timedelta(days=1)
                continue

            if not date_in_pattern(
                current_date,
                block.effective_start,
                block.recurrence_frequency,
                max(1, block.recurrence_interval),
                block.weekly_schedule,
            ):
                current_date += dt.timedelta(days=1)
                continue

            if is_daily:
                windows = block.time_windows
            else:
                day_name = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][current_date.weekday()]
                windows = block.weekly_schedule.get(day_name, [])

            # Skip this date if an override narrows availability and hold is outside it
            if current_date in override_map:
                ovr_windows = override_map[current_date]
                if _block_outside_override(windows, ovr_windows):
                    current_date += dt.timedelta(days=1)
                    continue

            for window in windows:
                starts_at = to_utc(localize_naive(datetime.combine(current_date, window.start), tz))
                ends_at = to_utc(localize_naive(datetime.combine(current_date, window.end), tz))

                event = EventEffect(
                    calendar_id=calendar_id,
                    title=title,
                    starts_at=starts_at,
                    ends_at=ends_at,
                ).create()
                effects.append(event)
                event_count += 1

            current_date += dt.timedelta(days=1)

    log.info(
        "_build_hold_block_events: provider=%s hold_type=%s events=%d range=%s..%s locations=%s",
        block.provider_id, block.hold_type, event_count, range_start, range_end, block.location_ids,
    )
    return effects


def build_hold_block_refresh_effects(block: RecurringBlock) -> list[Effect]:
    """Refresh hold block events: delete existing and recreate for the rolling window.

    Called by the cron to advance the hold window daily — releasing dates that
    should now be available and adding new blocked dates at the far end.
    """
    effects: list[Effect] = []

    # Delete existing hold block events (legacy and new title formats)
    cal_ids = [c.id for c in get_admin_calendars(block.provider_id)]
    if cal_ids:
        for prefix in HOLD_TITLE_PREFIXES:
            for evt in EventModel.objects.filter(
                calendar__id__in=cal_ids,
                title__startswith=prefix,
                is_cancelled=False,
            ):
                effects.append(EventEffect(event_id=str(evt.id)).delete())

    # Recreate for current window
    effects.extend(_build_hold_block_events(block))
    return effects


def build_delete_recurring_block_effects(provider_id: str, block: RecurringBlock | None = None) -> list[Effect]:
    """Delete recurring block events from the provider's Admin calendars.

    If a specific block is given, first try stored event IDs, then fall back
    to matching by the block's actual title (reason). Also searches for
    the legacy RECURRING_BLOCK_TITLE to clean up orphaned events.
    """
    effects: list[Effect] = []

    if block:
        stored_ids = get_event_ids(block.id)
        if stored_ids:
            for eid in stored_ids:
                effects.append(EventEffect(event_id=eid).delete())
            log.info("build_delete_recurring_block_effects: block=%s, deleted %d events by stored IDs", block.id, len(effects))
            # Also clean up any hold block events
            cal_ids = [c.id for c in get_admin_calendars(provider_id)]
            if block.hold_type != "none" and cal_ids:
                for prefix in HOLD_TITLE_PREFIXES:
                    for evt in EventModel.objects.filter(
                        calendar__id__in=cal_ids,
                        title__startswith=prefix,
                        is_cancelled=False,
                    ):
                        effects.append(EventEffect(event_id=str(evt.id)).delete())
            return effects

        # Fall back: match by the block's actual title AND legacy title
        title = block.reason if block.reason else "Blocked"
        titles_to_delete = [title]
        if RECURRING_BLOCK_TITLE != title:
            titles_to_delete.append(RECURRING_BLOCK_TITLE)
        cal_ids = [c.id for c in get_admin_calendars(provider_id)]
        if cal_ids:
            for evt in EventModel.objects.filter(
                calendar__id__in=cal_ids,
                title__in=titles_to_delete,
                is_cancelled=False,
            ):
                effects.append(EventEffect(event_id=str(evt.id)).delete())
            # Also clean up hold block events
            if block.hold_type != "none":
                for prefix in HOLD_TITLE_PREFIXES:
                    for evt in EventModel.objects.filter(
                        calendar__id__in=cal_ids,
                        title__startswith=prefix,
                        is_cancelled=False,
                    ):
                        effects.append(EventEffect(event_id=str(evt.id)).delete())
    else:
        # No specific block — search by legacy title
        cal_ids = [c.id for c in get_admin_calendars(provider_id)]
        if cal_ids:
            for evt in EventModel.objects.filter(
                calendar__id__in=cal_ids,
                title=RECURRING_BLOCK_TITLE,
                is_cancelled=False,
            ):
                effects.append(EventEffect(event_id=str(evt.id)).delete())

    if effects:
        log.info("build_delete_recurring_block_effects: provider=%s, %d delete effects", provider_id, len(effects))
    return effects
