"""Overlap detection for availability rules."""

from __future__ import annotations

from datetime import date, time, timedelta

from provider_availability.engine.models import (
    DateOverride,
    ProviderAvailabilityRule,
    TimeWindow,
    date_in_pattern,
)
from provider_availability.engine.storage import get_rules_for_provider


_OVERLAP_PROBE_HORIZON_DAYS = 366  # one full year + a day, enough to find common occurrences
_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _fmt_time(t: time) -> str:
    """9:00 AM"""
    return t.strftime("%I:%M %p").lstrip("0")


def _fmt_window(w: TimeWindow) -> str:
    return f"{_fmt_time(w.start)} \u2013 {_fmt_time(w.end)}"


def _fmt_date(d: date) -> str:
    """Wed, Nov 11, 2026"""
    return f"{_DAY_ABBR[d.weekday()]}, {d.strftime('%b')} {d.day}, {d.year}"


def _rule_name(rule: ProviderAvailabilityRule) -> str:
    """How a conflict message names the saved rule it clashes with."""
    if rule.is_round:
        return f"the facility round at {rule.facility_name}" if rule.facility_name else "a facility round"
    return f"availability \u201c{rule.reason}\u201d" if rule.reason else "existing availability"


def _lcm(a: int, b: int) -> int:
    """Least common multiple (the sandbox doesn't allow importing math)."""
    x, y = a, b
    while y:
        x, y = y, x % y
    return a * b // x


def _period_days(rule: ProviderAvailabilityRule) -> int:
    """Days until the rule's pattern repeats."""
    interval = max(1, rule.recurrence_interval)
    return interval if rule.recurrence_frequency == "daily" else 7 * interval


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
    existing_rules: list[ProviderAvailabilityRule] | None = None,
) -> str | None:
    """Check if a rule overlaps with existing rules for the same provider.

    Returns a conflict description string if overlap found, else None.

    Pass existing_rules (the provider's saved rules) to skip the per-call cache
    read — callers validating many rules at once should fetch once and reuse.

    Honors recurrence frequency / interval — two rules with non-coinciding
    occurrences (e.g. weekly interval=2 anchored on alternating weeks) are
    not flagged.
    """
    if existing_rules is None:
        existing_rules = get_rules_for_provider(rule.provider_id)

    for existing in existing_rules:
        if existing.id == exclude_rule_id:
            continue
        if not existing.is_active:
            continue

        # 0. One-day overrides on either rule, against the other rule's hours that day.
        override_msg = _override_conflict(rule, existing, existing) or _override_conflict(existing, rule, existing)
        if override_msg:
            return override_msg

        # 1. Check effective date range overlap
        if not _date_ranges_overlap(
            rule.effective_start, rule.effective_end,
            existing.effective_start, existing.effective_end,
        ):
            continue

        # 2. Every weekday where both rules have an occurrence and their hours meet.
        #    Walks one full cycle of the two patterns, so bi-weekly rules on
        #    alternating weeks are not flagged and no shared weekday is skipped.
        conflicts = _weekday_conflicts(rule, existing)
        if conflicts:
            return _conflict_message(conflicts, existing)

    return None


def _weekday_conflicts(
    rule: ProviderAvailabilityRule, existing: ProviderAvailabilityRule
) -> dict[int, tuple[TimeWindow, TimeWindow]]:
    """First clashing pair of hours per weekday (0 = Monday) across one shared cycle."""
    start = _shared_active_date(rule, existing)
    if start is None:
        return {}
    end = start + timedelta(days=min(_lcm(_period_days(rule), _period_days(existing)), _OVERLAP_PROBE_HORIZON_DAYS))
    for bound in (rule.effective_end, existing.effective_end):
        if bound is not None:
            end = min(end, bound + timedelta(days=1))
    found: dict[int, tuple[TimeWindow, TimeWindow]] = {}
    day = start
    while day < end:
        if day.weekday() not in found and _in_pattern(rule, day) and _in_pattern(existing, day):
            pair = next(
                ((nw, ew) for nw in _windows_for_day(rule, day)[1] for ew in _windows_for_day(existing, day)[1] if nw.overlaps(ew)),
                None,
            )
            if pair:
                found[day.weekday()] = pair
        day += timedelta(days=1)
    return found


def _in_pattern(rule: ProviderAvailabilityRule, day: date) -> bool:
    return date_in_pattern(
        day, rule.effective_start, rule.recurrence_frequency, rule.recurrence_interval, rule.weekly_schedule
    )


def _conflict_message(conflicts: dict[int, tuple[TimeWindow, TimeWindow]], existing: ProviderAvailabilityRule) -> str:
    """\"Overlaps the facility round at X on Mon, Wed, Fri: 9:00 AM – 5:00 PM conflicts with 9:00 AM – 5:00 PM.\""""
    days = sorted(conflicts)
    pairs = {(_fmt_window(nw), _fmt_window(ew)) for nw, ew in conflicts.values()}
    label = "every day" if len(days) == 7 else ", ".join(_DAY_ABBR[d] for d in days)
    if len(pairs) == 1:
        new_hours, saved_hours = next(iter(pairs))
        return f"Overlaps {_rule_name(existing)} on {label}: {new_hours} conflicts with {saved_hours}."
    detail = "; ".join(
        f"{_DAY_ABBR[d]} {_fmt_window(conflicts[d][0])} conflicts with {_fmt_window(conflicts[d][1])}" for d in days
    )
    return f"Overlaps {_rule_name(existing)} on {label}: {detail}."


def _hours_on(rule: ProviderAvailabilityRule, day: date) -> list[TimeWindow]:
    """The hours a rule actually keeps on one date: its override for that date, else its schedule."""
    for o in rule.date_overrides:
        if o.date == day:
            return [] if o.is_closed else list(o.time_windows)
    if rule.effective_start and day < rule.effective_start:
        return []
    if rule.effective_end and day > rule.effective_end:
        return []
    if not date_in_pattern(
        day, rule.effective_start, rule.recurrence_frequency,
        max(1, rule.recurrence_interval), rule.weekly_schedule,
    ):
        return []
    return _windows_for_day(rule, day)[1]


def check_override_overlap(
    rule: ProviderAvailabilityRule,
    override: DateOverride,
    existing_rules: list[ProviderAvailabilityRule] | None = None,
) -> str | None:
    """Check a date override against the provider's other active rules on that date.

    Rule saves already keep a provider's rules apart; an override could still
    stretch one rule into another's hours on a single day, where both would
    claim the same time (and the longer lead time would cover both).
    """
    if override.is_closed:
        return None
    if existing_rules is None:
        existing_rules = get_rules_for_provider(rule.provider_id)
    only_this = ProviderAvailabilityRule(id=rule.id, provider_id=rule.provider_id, date_overrides=[override])
    for other in existing_rules:
        if other.id == rule.id or not other.is_active:
            continue
        msg = _override_conflict(only_this, other, other)
        if msg:
            return msg
    return None


def _override_conflict(
    a: ProviderAvailabilityRule, b: ProviderAvailabilityRule, saved: ProviderAvailabilityRule
) -> str | None:
    """A date override on rule ``a`` whose hours overlap rule ``b``'s hours that day.

    ``saved`` is the saved rule the message names, whichever side the override is on.
    """
    for o in a.date_overrides:
        if o.is_closed:
            continue
        for ow in _hours_on(b, o.date):
            for nw in o.time_windows:
                if nw.overlaps(ow):
                    return (
                        f"Overlaps {_rule_name(saved)} on {_fmt_date(o.date)}: "
                        f"{_fmt_window(nw)} conflicts with {_fmt_window(ow)}."
                    )
    return None
