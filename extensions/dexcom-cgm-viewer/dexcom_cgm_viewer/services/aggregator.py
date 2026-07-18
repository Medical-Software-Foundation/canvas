"""Pure aggregations: time-in-range, GMI, hypo/hyper excursions.

Everything in this module is deterministic and dependency-free so it can be
unit-tested without database or HTTP fixtures.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from dexcom_cgm_viewer.services.settings import (
    EXCURSION_GAP_MINUTES,
    HYPER_EVENT_THRESHOLD_MGDL,
    TIR_HIGH_MGDL,
    TIR_LOW_MGDL,
)


@dataclass
class Reading:
    """Lightweight reading shape used by aggregations.

    The data layer (``DexcomEgv``) maps directly to this without any joins.
    ``value_mgdl`` may legitimately be ``None`` for sensor blackout windows;
    aggregation skips those rows.

    Field types use ``Any`` because the Canvas plugin sandbox rejects PEP-604
    union annotations (``int | None``) on dataclass fields.
    """

    display_time: Any
    value_mgdl: Any


@dataclass
class DailyAggregate:
    """One day's worth of summary metrics for a single patient."""

    date: Any
    avg_glucose_mgdl: float
    gmi_percent: float
    tir_low_pct: float
    tir_target_pct: float
    tir_high_pct: float
    hypo_events: int
    hyper_events: int
    reading_count: int


def gmi_percent(avg_glucose_mgdl: float) -> float:
    """ADA glucose-management-indicator estimate of A1c, rounded to 0.1."""
    return round(3.31 + 0.02392 * avg_glucose_mgdl, 1)


def time_in_range(values: Sequence[int]) -> tuple[float, float, float]:
    """Return (low %, target %, high %) for a sequence of mg/dL readings."""
    total = len(values)
    if total == 0:
        return 0.0, 0.0, 0.0
    low = sum(1 for v in values if v < TIR_LOW_MGDL)
    high = sum(1 for v in values if v > TIR_HIGH_MGDL)
    target = total - low - high
    return (
        round(low * 100 / total, 1),
        round(target * 100 / total, 1),
        round(high * 100 / total, 1),
    )


def count_excursions(readings: Sequence[Reading], *, threshold: int, low: bool) -> int:
    """Count contiguous excursions across ``threshold``.

    Two consecutive in-violation readings separated by more than
    ``EXCURSION_GAP_MINUTES`` count as separate events, matching ADA-style
    event counting from CGM data.
    """
    events = 0
    in_excursion = False
    last_time: dt.datetime | None = None
    for reading in readings:
        if reading.value_mgdl is None:
            continue
        violating = reading.value_mgdl < threshold if low else reading.value_mgdl > threshold
        if not violating:
            in_excursion = False
            last_time = reading.display_time
            continue
        if not in_excursion:
            events += 1
            in_excursion = True
        elif last_time is not None:
            gap_minutes = (reading.display_time - last_time).total_seconds() / 60
            if gap_minutes > EXCURSION_GAP_MINUTES:
                events += 1
        last_time = reading.display_time
    return events


def aggregate_day(date: dt.date, readings: Sequence[Reading]) -> DailyAggregate:
    """Compute one day's aggregate from its readings (already filtered by date)."""
    cleaned = [r for r in readings if r.value_mgdl is not None]
    values: list[int] = [r.value_mgdl for r in cleaned if r.value_mgdl is not None]
    if not values:
        return DailyAggregate(
            date=date,
            avg_glucose_mgdl=0.0,
            gmi_percent=0.0,
            tir_low_pct=0.0,
            tir_target_pct=0.0,
            tir_high_pct=0.0,
            hypo_events=0,
            hyper_events=0,
            reading_count=0,
        )
    avg = sum(values) / len(values)
    low_pct, target_pct, high_pct = time_in_range(values)
    sorted_readings = sorted(cleaned, key=lambda r: r.display_time)
    return DailyAggregate(
        date=date,
        avg_glucose_mgdl=round(avg, 1),
        gmi_percent=gmi_percent(avg),
        tir_low_pct=low_pct,
        tir_target_pct=target_pct,
        tir_high_pct=high_pct,
        hypo_events=count_excursions(sorted_readings, threshold=TIR_LOW_MGDL, low=True),
        hyper_events=count_excursions(
            sorted_readings, threshold=HYPER_EVENT_THRESHOLD_MGDL, low=False
        ),
        reading_count=len(values),
    )


def aggregate_range(readings: Iterable[Reading]) -> dict[dt.date, DailyAggregate]:
    """Bucket ``readings`` by ``display_time.date()`` and aggregate each day."""
    by_day: dict[dt.date, list[Reading]] = defaultdict(list)
    for reading in readings:
        by_day[reading.display_time.date()].append(reading)
    return {day: aggregate_day(day, items) for day, items in by_day.items()}


def aggregate_window(readings: Sequence[Reading]) -> DailyAggregate | None:
    """Treat ``readings`` as one bucket and compute a window-wide aggregate.

    Used for the chart's stats row across the user-selected range. Returns
    ``None`` when there are no usable readings.
    """
    cleaned = [r for r in readings if r.value_mgdl is not None]
    if not cleaned:
        return None
    earliest = min(r.display_time for r in cleaned).date()
    return aggregate_day(earliest, cleaned)
