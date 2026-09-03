"""Recurrence rule schema, validator, legacy translation, and projector.

Pure data layer for the scheduling modal recurrence work. Holds the flat
schema, the wire form parser, the backwards compatible translation from
the legacy cadence string, and project_dates which lays a rule onto the
calendar.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Any


MAX_OCCURRENCES = 52

_WEEKDAY_ORDER = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_WEEKDAY_INDEX = {code: i for i, code in enumerate(_WEEKDAY_ORDER)}


class RecurrenceValidationError(ValueError):
    """Raised when a wire form recurrence payload fails validation."""


class RecurrenceUnit(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class Weekday(str, Enum):
    MO = "MO"
    TU = "TU"
    WE = "WE"
    TH = "TH"
    FR = "FR"
    SA = "SA"
    SU = "SU"


@dataclass(frozen=True)
class RecurrenceInterval:
    value: int
    unit: RecurrenceUnit


@dataclass(frozen=True)
class RecurrenceEndCount:
    count: int


@dataclass(frozen=True)
class RecurrenceEndUntil:
    until: date


RecurrenceEnd = RecurrenceEndCount | RecurrenceEndUntil


@dataclass(frozen=True)
class RecurrenceRule:
    interval: RecurrenceInterval
    end: RecurrenceEnd
    weekdays: tuple[Weekday, ...] = field(default_factory=tuple)
    exclusions: tuple[date, ...] = field(default_factory=tuple)


def _today() -> date:
    """Return the current local date. Extracted for test mockability."""
    return date.today()


def parse_recurrence(payload: dict[str, Any]) -> RecurrenceRule:
    """Validate and parse a wire form recurrence rule.

    Raises RecurrenceValidationError on malformed input. The shape
    matches the canonical flat recurrence schema.
    """
    if not isinstance(payload, dict):
        raise RecurrenceValidationError("recurrence must be an object")

    interval = _parse_interval(payload.get("interval"))
    end = _parse_end(payload.get("end"))
    weekdays = _parse_weekdays(payload.get("weekdays"), interval.unit)
    exclusions = _parse_exclusions(payload.get("exclusions"))

    return RecurrenceRule(
        interval=interval,
        end=end,
        weekdays=weekdays,
        exclusions=exclusions,
    )


def from_legacy_cadence(cadence: str, occurrences: int) -> RecurrenceRule:
    """Translate a legacy cadence string into the canonical flat rule.

    Used by /availability and /candidate-times during the transitional
    release. The four legacy strings map to canonical flat objects.
    """
    if not isinstance(cadence, str):
        raise RecurrenceValidationError("cadence must be a string")
    if not isinstance(occurrences, int) or isinstance(occurrences, bool):
        raise RecurrenceValidationError("occurrences must be an integer")
    if occurrences < 1:
        raise RecurrenceValidationError("occurrences must be at least 1")

    capped = min(occurrences, MAX_OCCURRENCES)

    if cadence == "single":
        return RecurrenceRule(
            interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.DAY),
            end=RecurrenceEndCount(count=1),
        )
    if cadence == "weekly":
        return RecurrenceRule(
            interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.WEEK),
            end=RecurrenceEndCount(count=capped),
        )
    if cadence == "biweekly":
        return RecurrenceRule(
            interval=RecurrenceInterval(value=2, unit=RecurrenceUnit.WEEK),
            end=RecurrenceEndCount(count=capped),
        )
    if cadence == "monthly":
        return RecurrenceRule(
            interval=RecurrenceInterval(value=1, unit=RecurrenceUnit.MONTH),
            end=RecurrenceEndCount(count=capped),
        )

    raise RecurrenceValidationError(f"unknown cadence: {cadence!r}")


def _parse_interval(raw: Any) -> RecurrenceInterval:
    if not isinstance(raw, dict):
        raise RecurrenceValidationError("interval must be an object")

    value = raw.get("value")
    unit = raw.get("unit")

    if not isinstance(value, int) or isinstance(value, bool):
        raise RecurrenceValidationError("interval.value must be an integer")
    if value < 1:
        raise RecurrenceValidationError("interval.value must be at least 1")

    if not isinstance(unit, str):
        raise RecurrenceValidationError("interval.unit must be a string")
    try:
        unit_enum = RecurrenceUnit(unit)
    except ValueError:
        raise RecurrenceValidationError(
            f"interval.unit must be one of day, week, month, got {unit!r}"
        ) from None

    return RecurrenceInterval(value=value, unit=unit_enum)


def _parse_end(raw: Any) -> RecurrenceEnd:
    if not isinstance(raw, dict):
        raise RecurrenceValidationError("end must be an object")

    kind = raw.get("kind")
    if kind == "count":
        count = raw.get("count")
        if not isinstance(count, int) or isinstance(count, bool):
            raise RecurrenceValidationError("end.count must be an integer")
        if count < 1 or count > MAX_OCCURRENCES:
            raise RecurrenceValidationError(
                f"end.count must be between 1 and {MAX_OCCURRENCES}"
            )
        return RecurrenceEndCount(count=count)

    if kind == "until":
        until_raw = raw.get("until")
        if not isinstance(until_raw, str):
            raise RecurrenceValidationError("end.until must be an ISO date string")
        try:
            until = date.fromisoformat(until_raw)
        except ValueError:
            raise RecurrenceValidationError(
                f"end.until must be an ISO date, got {until_raw!r}"
            ) from None
        if until < _today():
            raise RecurrenceValidationError("end.until must not be in the past")
        return RecurrenceEndUntil(until=until)

    raise RecurrenceValidationError(
        f"end.kind must be 'count' or 'until', got {kind!r}"
    )


def _parse_weekdays(raw: Any, unit: RecurrenceUnit) -> tuple[Weekday, ...]:
    if raw is None:
        return ()

    if not isinstance(raw, list):
        raise RecurrenceValidationError("weekdays must be an array")

    if not raw:
        return ()

    if unit is not RecurrenceUnit.WEEK:
        raise RecurrenceValidationError(
            "weekdays is only allowed when interval.unit is 'week'"
        )

    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise RecurrenceValidationError("weekdays entries must be strings")
        if entry in seen:
            raise RecurrenceValidationError(f"duplicate weekday: {entry!r}")
        try:
            Weekday(entry)
        except ValueError:
            raise RecurrenceValidationError(
                f"weekdays entries must be one of MO, TU, WE, TH, FR, SA, SU, "
                f"got {entry!r}"
            ) from None
        seen.add(entry)

    ordered = tuple(Weekday(code) for code in _WEEKDAY_ORDER if code in seen)
    return ordered


def _parse_exclusions(raw: Any) -> tuple[date, ...]:
    if raw is None:
        return ()

    if not isinstance(raw, list):
        raise RecurrenceValidationError("exclusions must be an array")

    parsed: set[date] = set()
    for entry in raw:
        if not isinstance(entry, str):
            raise RecurrenceValidationError("exclusions entries must be ISO date strings")
        try:
            parsed.add(date.fromisoformat(entry))
        except ValueError:
            raise RecurrenceValidationError(
                f"exclusions entries must be ISO dates, got {entry!r}"
            ) from None

    return tuple(sorted(parsed))


# ---------------------------------------------------------------------------
# Projector
# ---------------------------------------------------------------------------


def project_dates(start: date, rule: RecurrenceRule) -> list[date]:
    """Lay the rule onto the calendar starting at start.

    Returns ordered, unique dates with rule.exclusions removed and
    capped at MAX_OCCURRENCES. Past dates are not
    filtered. The endpoint enforces past date policy on start.
    """
    candidates = list(_iter_candidates(start, rule))
    if rule.exclusions:
        excluded = set(rule.exclusions)
        candidates = [d for d in candidates if d not in excluded]
    return candidates


def _iter_candidates(start: date, rule: RecurrenceRule):
    if rule.interval.unit is RecurrenceUnit.DAY:
        yield from _iter_simple(start, rule, rule.interval.value)
    elif rule.interval.unit is RecurrenceUnit.WEEK:
        if rule.weekdays:
            yield from _iter_week_with_weekdays(start, rule)
        else:
            yield from _iter_simple(start, rule, rule.interval.value * 7)
    else:
        yield from _iter_month(start, rule)


def _iter_simple(
    start: date, rule: RecurrenceRule, step_days: int
):
    cap = _resolve_count_cap(rule)
    step = timedelta(days=step_days)
    d = start
    count = 0
    while count < cap:
        if not _within_until(d, rule):
            return
        yield d
        count += 1
        d += step


def _iter_week_with_weekdays(
    start: date, rule: RecurrenceRule
):
    target_offsets = sorted({_WEEKDAY_INDEX[w.value] for w in rule.weekdays})
    cap = _resolve_count_cap(rule)
    interval_weeks = rule.interval.value

    anchor_zero = start - timedelta(days=start.weekday())
    week_idx = 0
    count = 0

    while count < cap:
        week_start = anchor_zero + timedelta(
            days=week_idx * interval_weeks * 7
        )
        for offset in target_offsets:
            candidate = week_start + timedelta(days=offset)
            if week_idx == 0 and candidate < start:
                continue
            if not _within_until(candidate, rule):
                return
            yield candidate
            count += 1
            if count >= cap:
                return
        week_idx += 1


def _iter_month(start: date, rule: RecurrenceRule):
    cap = _resolve_count_cap(rule)
    step_months = rule.interval.value
    count = 0
    i = 0
    while count < cap:
        d = _add_months_clamped(start, i * step_months)
        if not _within_until(d, rule):
            return
        yield d
        count += 1
        i += 1


def _resolve_count_cap(rule: RecurrenceRule) -> int:
    if isinstance(rule.end, RecurrenceEndCount):
        return min(rule.end.count, MAX_OCCURRENCES)
    return MAX_OCCURRENCES


def _within_until(d: date, rule: RecurrenceRule) -> bool:
    if isinstance(rule.end, RecurrenceEndUntil):
        return d <= rule.end.until
    return True


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in (year, month) without `calendar` import.

    Stand in for `calendar.monthrange(year, month)[1]`. The `calendar`
    module is not on the Canvas plugin sandbox import allowlist.
    """
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    return (first_of_next - timedelta(days=1)).day


def _add_months_clamped(d: date, months: int) -> date:
    if months == 0:
        return d
    total = (d.month - 1) + months
    new_year = d.year + total // 12
    new_month = total % 12 + 1
    last_day = _days_in_month(new_year, new_month)
    return date(new_year, new_month, min(d.day, last_day))


# ---------------------------------------------------------------------------
# Candidate first date iterator
# ---------------------------------------------------------------------------


def iter_candidate_first_dates(
    rule: RecurrenceRule, window_start: date, window_end: date
):
    """Yield each date inside [window_start, window_end] that may begin rule.

    For a unit week rule with explicit weekdays, only dates whose weekday is
    in the rule's weekdays set are candidates. For unit day, unit week without
    weekdays, and unit month, every date in the window is a candidate.
    """
    if window_end < window_start:
        return

    weekday_filter: set[int] | None = None
    if rule.interval.unit is RecurrenceUnit.WEEK and rule.weekdays:
        weekday_filter = {_WEEKDAY_INDEX[w.value] for w in rule.weekdays}

    d = window_start
    while d <= window_end:
        if weekday_filter is None or d.weekday() in weekday_filter:
            yield d
        d += timedelta(days=1)
