"""Map raw Oura API v2 records onto the plugin's normalized daily payloads.

Pure functions: no ``canvas_sdk``, no Django, no I/O. The chart reads only the
keys produced here and never raw Oura fields, so an upstream schema change is
absorbed in this one module.

Values are range-checked before they can reach the chart. Oura uses 0 as a
placeholder in some fields when a measurement is missing (an SpO2 of 0% or a
heart rate of 0 bpm is not a reading), and a wellness panel that renders a
placeholder as a value is worse than one that shows a gap. Booleans are
rejected even though Python treats them as integers.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from oura_ring_viewer.services.settings import (
    FAMILY_ACTIVITY,
    FAMILY_READINESS,
    FAMILY_SLEEP,
    FAMILY_SPO2,
)
from oura_ring_viewer.services.time_utils import parse_day

# Sleep period types that represent actual sleep. "deleted" is a tombstone and
# "rest" marks rest mode; neither is a night's sleep.
_SLEEP_PERIOD_TYPES = frozenset({"long_sleep", "sleep", "late_nap"})
_PRIMARY_SLEEP_TYPE = "long_sleep"

_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class NormalizedDay:
    """One normalized summary: a patient-agnostic (day, family, payload)."""

    day: dt.date
    family: str
    payload: dict[str, Any]


def normalize_sleep(
    daily_sleep: Iterable[Any], sleep_periods: Iterable[Any]
) -> list[NormalizedDay]:
    """Combine the daily sleep score with the day's main sleep period.

    ``daily_sleep`` carries the score; the raw measurements (duration, HRV,
    overnight heart rate) live on the sleep periods. When a day has several
    periods (a night plus naps), the main overnight ``long_sleep`` wins, then
    the longest period.
    """
    scores: dict[dt.date, int | None] = {}
    for record in daily_sleep:
        day = _day_of(record)
        if day is not None:
            scores[day] = _int(record.get("score"), 0, 100, allow_low=False)

    primary: dict[dt.date, dict[str, Any]] = {}
    for record in sleep_periods:
        day = _day_of(record)
        if day is None or record.get("type") not in _SLEEP_PERIOD_TYPES:
            continue
        current = primary.get(day)
        if current is None or _period_rank(record) > _period_rank(current):
            primary[day] = record

    days: list[NormalizedDay] = []
    for day in sorted(scores.keys() | primary.keys()):
        period = primary.get(day, {})
        payload = {
            "score": scores.get(day),
            "total_sleep_seconds": _int(
                period.get("total_sleep_duration"), 0, _SECONDS_PER_DAY, allow_low=False
            ),
            "efficiency": _int(period.get("efficiency"), 0, 100, allow_low=False),
            "average_hrv_ms": _int(period.get("average_hrv"), 0, 300, allow_low=False),
            "lowest_heart_rate_bpm": _int(
                period.get("lowest_heart_rate"), 0, 250, allow_low=False
            ),
            "average_heart_rate_bpm": _round(
                _num(period.get("average_heart_rate"), 0, 250, allow_low=False), 1
            ),
        }
        if _has_value(payload):
            days.append(NormalizedDay(day=day, family=FAMILY_SLEEP, payload=payload))
    return days


def normalize_readiness(records: Iterable[Any]) -> list[NormalizedDay]:
    """Daily readiness: score and body temperature deviation."""
    return _per_day(
        records,
        FAMILY_READINESS,
        lambda r: {
            "score": _int(r.get("score"), 0, 100, allow_low=False),
            "temperature_deviation_c": _round(
                _num(r.get("temperature_deviation"), -10, 10), 2
            ),
        },
    )


def normalize_activity(records: Iterable[Any]) -> list[NormalizedDay]:
    """Daily activity: score, steps and active calories.

    Zero steps and zero active calories are real values on a sedentary day, so
    unlike the physiological measures they are kept.
    """
    return _per_day(
        records,
        FAMILY_ACTIVITY,
        lambda r: {
            "score": _int(r.get("score"), 0, 100, allow_low=False),
            "steps": _int(r.get("steps"), 0, 200_000),
            "active_calories": _int(r.get("active_calories"), 0, 20_000),
        },
    )


def normalize_spo2(records: Iterable[Any]) -> list[NormalizedDay]:
    """Overnight SpO2 average and breathing disturbance index."""

    def build(record: dict[str, Any]) -> dict[str, Any]:
        spo2 = record.get("spo2_percentage")
        average = spo2.get("average") if isinstance(spo2, dict) else None
        return {
            "average_pct": _round(_num(average, 0, 100, allow_low=False), 1),
            "breathing_disturbance_index": _int(
                record.get("breathing_disturbance_index"), 0, 200
            ),
        }

    return _per_day(records, FAMILY_SPO2, build)


def _per_day(
    records: Iterable[Any],
    family: str,
    build: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[NormalizedDay]:
    """Build one payload per day; a later record for the same day wins.

    An empty payload is skipped rather than stored, so a placeholder record can
    never erase a real reading that arrived earlier for the same day.
    """
    by_day: dict[dt.date, dict[str, Any]] = {}
    for record in records:
        day = _day_of(record)
        if day is None:
            continue
        payload = build(record)
        if _has_value(payload):
            by_day[day] = payload
    return [
        NormalizedDay(day=day, family=family, payload=by_day[day])
        for day in sorted(by_day)
    ]


def _day_of(record: Any) -> dt.date | None:
    if not isinstance(record, dict):
        return None
    return parse_day(record.get("day"))


def _period_rank(record: dict[str, Any]) -> tuple[bool, int]:
    duration = _int(record.get("total_sleep_duration"), 0, _SECONDS_PER_DAY) or 0
    return (record.get("type") == _PRIMARY_SLEEP_TYPE, duration)


def _has_value(payload: dict[str, Any]) -> bool:
    """A payload with nothing measurable is not worth a row."""
    return any(value is not None for value in payload.values())


def _num(value: Any, low: float, high: float, *, allow_low: bool = True) -> float | None:
    """Return ``value`` as a float if it is a real, in-range number, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    # NaN check without math.isnan: the Canvas sandbox does not allow importing math.
    if number != number:  # noqa: PLR0124
        return None
    if number < low or number > high or (number == low and not allow_low):
        return None
    return number


def _int(value: Any, low: float, high: float, *, allow_low: bool = True) -> int | None:
    number = _num(value, low, high, allow_low=allow_low)
    return None if number is None else round(number)


def _round(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)
