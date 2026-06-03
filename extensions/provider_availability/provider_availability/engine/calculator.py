"""Availability calculation engine.

Computes available time slots by:
1. Starting with the provider's weekly schedule template
2. Checking date-specific overrides before falling back to weekly schedule
3. Subtracting existing appointments to find open windows
4. Subtracting Canvas Schedule Events and plugin-managed admin blocks
5. Applying buffer times around existing bookings
6. Enforcing booking interval constraints (lead time, max advance, granularity)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data import Event

from provider_availability.engine.models import (
    AvailableSlot,
    DAYS_OF_WEEK,
    ProviderAvailabilityRule,
    TimeWindow,
    date_in_pattern,
)
from provider_availability.engine.provider_resolver import get_provider_display
from provider_availability.engine.storage import get_blocks_for_provider, get_recurring_blocks_for_provider
from provider_availability.engine.tz_utils import provider_now, to_provider_naive


def calculate_available_slots(
    rule: ProviderAvailabilityRule,
    start_date: date,
    end_date: date,
    now: datetime | None = None,
) -> list[AvailableSlot]:
    """Calculate available slots for a rule within a date range."""
    if not rule.is_active:
        return []

    if now is None:
        now = provider_now(rule.provider_id).replace(tzinfo=None)

    # Enforce booking interval constraints on date range
    min_lead = timedelta(hours=rule.booking_interval.min_lead_hours)

    earliest_bookable = now + min_lead

    effective_start = max(
        datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0),
        earliest_bookable,
    )
    effective_end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    if effective_start >= effective_end:
        return []

    # Clamp to rule's effective date range
    if rule.effective_start:
        eff_start_dt = datetime(
            rule.effective_start.year, rule.effective_start.month, rule.effective_start.day,
            0, 0, 0,
        )
        effective_start = max(effective_start, eff_start_dt)
    if rule.effective_end:
        eff_end_dt = datetime(
            rule.effective_end.year, rule.effective_end.month, rule.effective_end.day,
            23, 59, 59,
        )
        effective_end = min(effective_end, eff_end_dt)

    if effective_start >= effective_end:
        return []

    # Fetch existing appointments for conflict detection
    # Use the first location_id for appointment filtering, or empty for wildcard
    first_location = rule.location_ids[0] if rule.location_ids else ""
    existing_appointments = _get_appointments(
        rule.provider_id,
        effective_start,
        effective_end,
        first_location,
    )

    # Build blocked intervals from appointments + buffers
    blocked_intervals = _build_blocked_intervals(
        existing_appointments,
        rule.buffer_minutes.pre,
        rule.buffer_minutes.post,
    )

    # Add Schedule Event blocks
    schedule_event_blocks = _get_schedule_event_blocks(
        rule.provider_id, effective_start, effective_end
    )
    blocked_intervals.extend(schedule_event_blocks)

    # Add plugin-managed admin blocks (normalize TZ to naive provider-TZ)
    admin_blocks = get_blocks_for_provider(rule.provider_id)
    for block in admin_blocks:
        block_start = to_provider_naive(block.start, rule.provider_id)
        block_end = to_provider_naive(block.end, rule.provider_id)
        if block_start < effective_end and block_end > effective_start:
            blocked_intervals.append((block_start, block_end))

    # Add hold-type recurring blocks (dynamically enforced, not via calendar events)
    today = now.date()
    recurring_blocks = get_recurring_blocks_for_provider(rule.provider_id)
    for rb in recurring_blocks:
        if not rb.is_active or rb.hold_type == "none":
            continue  # non-hold blocks handled via calendar events
        # Check effective date range
        if rb.effective_start and effective_end.date() < rb.effective_start:
            continue
        if rb.effective_end and effective_start.date() > rb.effective_end:
            continue
        current_date = effective_start.date()
        rb_freq = rb.recurrence_frequency
        rb_interval = rb.recurrence_interval
        while current_date <= effective_end.date():
            if rb.effective_start and current_date < rb.effective_start:
                current_date += timedelta(days=1)
                continue
            if rb.effective_end and current_date > rb.effective_end:
                break
            if not date_in_pattern(
                current_date, rb.effective_start, rb_freq, rb_interval, rb.weekly_schedule,
            ):
                current_date += timedelta(days=1)
                continue
            if rb_freq == "daily":
                day_windows = rb.time_windows
            else:
                day_name = DAYS_OF_WEEK[current_date.weekday()]
                day_windows = rb.weekly_schedule.get(day_name, [])
            for window in day_windows:
                should_block = False
                if rb.hold_type == "same_day" and current_date > today:
                    should_block = True
                elif rb.hold_type == "next_day" and current_date > today + timedelta(days=1):
                    should_block = True
                if should_block:
                    block_start = datetime.combine(current_date, window.start)
                    block_end = datetime.combine(current_date, window.end)
                    blocked_intervals.append((block_start, block_end))
            current_date += timedelta(days=1)

    # Build date override lookup
    override_lookup = {o.date: o for o in rule.date_overrides}

    # Generate slots day by day
    granularity = timedelta(minutes=rule.booking_interval.slot_granularity_minutes)
    slots: list[AvailableSlot] = []

    current_date = effective_start.date()
    rule_freq = rule.recurrence_frequency
    rule_interval = rule.recurrence_interval
    while current_date <= effective_end.date():
        # Check for date-specific override before weekly schedule
        override = override_lookup.get(current_date)
        if override is not None:
            if override.is_closed:
                current_date += timedelta(days=1)
                continue
            windows = override.time_windows
        elif not date_in_pattern(
            current_date, rule.effective_start, rule_freq, rule_interval, rule.weekly_schedule,
        ):
            current_date += timedelta(days=1)
            continue
        elif rule_freq == "daily":
            windows = rule.time_windows
        else:
            day_name = DAYS_OF_WEEK[current_date.weekday()]
            windows = rule.weekly_schedule.get(day_name, [])

        for window in windows:
            slot_start = datetime.combine(current_date, window.start)
            window_end = datetime.combine(current_date, window.end)

            while slot_start + granularity <= window_end:
                slot_end = slot_start + granularity

                # Check against effective time bounds
                if slot_start >= effective_start and slot_end <= effective_end:
                    # Check for conflicts with blocked intervals
                    if not _is_blocked(slot_start, slot_end, blocked_intervals):
                        slots.append(
                            AvailableSlot(
                                start=slot_start,
                                end=slot_end,
                                provider_id=rule.provider_id,
                                location_id=rule.location_ids[0] if rule.location_ids else "",
                                visit_type=rule.visit_types[0] if rule.visit_types else "",
                            )
                        )

                slot_start = slot_end

        current_date += timedelta(days=1)

    return slots


def get_available_slots_for_provider(
    rules: list[ProviderAvailabilityRule],
    start_date: date,
    end_date: date,
    location_id: str = "",
    visit_type: str = "",
    now: datetime | None = None,
) -> list[AvailableSlot]:
    """Calculate available slots across all rules for a provider.

    Optionally filter by location and/or visit type.
    """
    all_slots: list[AvailableSlot] = []

    for rule in rules:
        if location_id:
            if rule.location_ids and location_id not in rule.location_ids:
                continue
        if visit_type:
            if rule.visit_types and visit_type not in rule.visit_types:
                continue
        all_slots.extend(calculate_available_slots(rule, start_date, end_date, now))

    all_slots.sort(key=lambda s: s.start)
    return all_slots


def _get_appointments(
    provider_id: str,
    start: datetime,
    end: datetime,
    location_id: str = "",
) -> list[tuple[datetime, int]]:
    """Fetch existing appointments from Canvas data."""
    filters = {
        "provider__id": provider_id,
        "start_time__gte": start,
        "start_time__lte": end,
    }
    if location_id:
        filters["location__id"] = location_id

    appointments = Appointment.objects.filter(**filters).values_list(
        "start_time", "duration_minutes"
    )
    return [(to_provider_naive(appt_start, provider_id), duration) for appt_start, duration in appointments]


def _get_schedule_event_blocks(
    provider_id: str,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime]]:
    """Fetch Canvas Schedule Events that block the provider's time.

    Calendar titles are formatted as "{provider name}: {event type}",
    so we match by provider name prefix.
    """
    display = get_provider_display(provider_id)
    provider_name = display.get("name", "")
    if not provider_name:
        return []

    events = Event.objects.filter(
        calendar__title__startswith=provider_name + ":",
        starts_at__lt=end,
        ends_at__gt=start,
        is_cancelled=False,
    ).exclude(
        calendar__title__startswith=provider_name + ": Clinic"
    )
    return [(to_provider_naive(e.starts_at, provider_id), to_provider_naive(e.ends_at, provider_id)) for e in events]


def _build_blocked_intervals(
    appointments: list[tuple[datetime, int]],
    pre_buffer: int,
    post_buffer: int,
) -> list[tuple[datetime, datetime]]:
    """Build blocked time intervals from appointments with buffers."""
    blocked: list[tuple[datetime, datetime]] = []
    for appt_start, duration in appointments:
        block_start = appt_start - timedelta(minutes=pre_buffer)
        block_end = appt_start + timedelta(minutes=duration + post_buffer)
        blocked.append((block_start, block_end))
    return blocked


def _is_blocked(
    slot_start: datetime,
    slot_end: datetime,
    blocked_intervals: list[tuple[datetime, datetime]],
) -> bool:
    """Check if a slot overlaps with any blocked interval."""
    for block_start, block_end in blocked_intervals:
        if slot_start < block_end and block_start < slot_end:
            return True
    return False
