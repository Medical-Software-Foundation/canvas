"""Overlap detection for availability rules."""

from __future__ import annotations

from datetime import date, timedelta

from provider_availability.engine.models import (
    ProviderAvailabilityRule,
    TimeWindow,
    date_in_pattern,
)
from provider_availability.engine.storage import get_rules_for_provider


_OVERLAP_PROBE_HORIZON_DAYS = 366  # one full year + a day, enough to find common occurrences


def _date_ranges_overlap(
    a_start: date | None,
    a_end: date | None,
    b_start: date | None,
    b_end: date | None,
) -> bool:
    """Check if two date ranges overlap. None means unbounded."""
    # If a ends before b starts, no overlap
    if a_end is not None and b_start is not None and a_end < b_start:
        return False
    # If b ends before a starts, no overlap
    if b_end is not None and a_start is not None and b_end < a_start:
        return False
    return True


def _shared_active_date(
    rule_a: ProviderAvailabilityRule,
    rule_b: ProviderAvailabilityRule,
) -> date | None:
    """Return any single date on which both rules are in-pattern, or None.

    Walks at most _OVERLAP_PROBE_HORIZON_DAYS from the later effective_start.
    Used to verify that two rules whose date ranges overlap actually have
    a common occurrence under their respective recurrence intervals.
    """
    probe_start = max(
        rule_a.effective_start or date.min,
        rule_b.effective_start or date.min,
    )
    if probe_start == date.min:
        # both unbounded — first date in either rule's pattern works; just probe today
        probe_start = date.today()

    probe_end = date.max
    if rule_a.effective_end:
        probe_end = min(probe_end, rule_a.effective_end)
    if rule_b.effective_end:
        probe_end = min(probe_end, rule_b.effective_end)

    horizon = probe_start + timedelta(days=_OVERLAP_PROBE_HORIZON_DAYS)
    if horizon < probe_end:
        probe_end = horizon

    candidate = probe_start
    while candidate <= probe_end:
        in_a = date_in_pattern(
            candidate,
            rule_a.effective_start,
            rule_a.recurrence_frequency,
            rule_a.recurrence_interval,
            rule_a.weekly_schedule,
        )
        in_b = date_in_pattern(
            candidate,
            rule_b.effective_start,
            rule_b.recurrence_frequency,
            rule_b.recurrence_interval,
            rule_b.weekly_schedule,
        )
        if in_a and in_b:
            return candidate
        candidate += timedelta(days=1)
    return None


def _windows_for_day(rule: ProviderAvailabilityRule, day: date) -> tuple[str, list[TimeWindow]]:
    """Return (label, windows) describing the rule's time windows on a given date."""
    if rule.recurrence_frequency == "daily":
        return ("daily", rule.time_windows)
    from provider_availability.engine.models import DAYS_OF_WEEK
    day_name = DAYS_OF_WEEK[day.weekday()]
    return (day_name, rule.weekly_schedule.get(day_name, []))


def check_rule_overlap(
    rule: ProviderAvailabilityRule,
    exclude_rule_id: str = "",
) -> str | None:
    """Check if a rule overlaps with existing rules for the same provider.

    Returns a conflict description string if overlap found, else None.

    Honors recurrence frequency / interval — two rules with non-coinciding
    occurrences (e.g. weekly interval=2 anchored on alternating weeks) are
    not flagged.
    """
    existing_rules = get_rules_for_provider(rule.provider_id)

    for existing in existing_rules:
        if existing.id == exclude_rule_id:
            continue
        if not existing.is_active:
            continue

        # 1. Check effective date range overlap
        if not _date_ranges_overlap(
            rule.effective_start, rule.effective_end,
            existing.effective_start, existing.effective_end,
        ):
            continue

        # 2. Find a date when both rules are in-pattern. Without this, two
        #    bi-weekly rules anchored on alternating weeks would be flagged.
        shared_date = _shared_active_date(rule, existing)
        if shared_date is None:
            continue

        # 3. Check for overlapping time windows on that shared occurrence.
        new_label, new_windows = _windows_for_day(rule, shared_date)
        existing_label, existing_windows = _windows_for_day(existing, shared_date)
        for nw in new_windows:
            for ew in existing_windows:
                if nw.overlaps(ew):
                    if new_label == "daily" or existing_label == "daily":
                        label = shared_date.isoformat()
                    else:
                        label = new_label.capitalize()
                    return (
                        f"Overlapping availability on {label}: "
                        f"{nw.start.strftime('%H:%M')}-{nw.end.strftime('%H:%M')} "
                        f"conflicts with existing rule "
                        f"{ew.start.strftime('%H:%M')}-{ew.end.strftime('%H:%M')}"
                    )

    return None
