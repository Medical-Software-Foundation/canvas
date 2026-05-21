"""Pure aggregations over a list of glucose readings."""

from __future__ import annotations

import datetime as dt

from dexcom_cgm_viewer.lib.aggregator import (
    Reading,
    aggregate_day,
    aggregate_range,
    aggregate_window,
    count_excursions,
    gmi_percent,
    time_in_range,
)


def _r(offset_seconds: int, value: int, *, day: int = 1) -> Reading:
    base = dt.datetime(2026, 5, day, 8, 0, tzinfo=dt.timezone.utc)
    return Reading(
        display_time=base + dt.timedelta(seconds=offset_seconds),
        value_mgdl=value,
    )


def test_gmi_formula_matches_ada() -> None:
    # 154 mg/dL is the canonical reference: GMI ≈ 7.0%
    assert gmi_percent(154) == 7.0
    assert gmi_percent(180) == 7.6


def test_time_in_range_handles_empty() -> None:
    assert time_in_range([]) == (0.0, 0.0, 0.0)


def test_time_in_range_buckets_correctly() -> None:
    values = [60, 70, 100, 150, 180, 200]  # 1 low, 4 target, 1 high
    low, target, high = time_in_range(values)
    assert low == round(100 / 6, 1)
    assert target == round(400 / 6, 1)
    assert high == round(100 / 6, 1)


def test_count_excursions_counts_two_contiguous_low_runs_separated_by_in_range() -> None:
    # First low run (0–5min), recovers (10min), then a second low run starts (60min onward).
    readings = [
        _r(0, 60),
        _r(5 * 60, 65),
        _r(10 * 60, 100),
        _r(60 * 60, 50),
        _r(65 * 60, 55),
    ]
    assert count_excursions(readings, threshold=70, low=True) == 2


def test_count_excursions_skips_none_values() -> None:
    readings = [
        Reading(display_time=dt.datetime(2026, 5, 1, 8, 0, tzinfo=dt.timezone.utc),
                value_mgdl=None),  # type: ignore[arg-type]
        _r(5 * 60, 60),
    ]
    assert count_excursions(readings, threshold=70, low=True) == 1


def test_count_excursions_handles_high_threshold() -> None:
    readings = [_r(0, 260), _r(5 * 60, 270)]
    assert count_excursions(readings, threshold=250, low=False) == 1


def test_count_excursions_starts_new_event_after_long_gap_within_run() -> None:
    # Both readings are below threshold but separated by >15 min — counts as 2.
    readings = [_r(0, 60), _r(20 * 60, 65)]
    assert count_excursions(readings, threshold=70, low=True) == 2


def test_aggregate_day_empty_returns_zeros() -> None:
    aggregate = aggregate_day(dt.date(2026, 5, 1), [])
    assert aggregate.reading_count == 0
    assert aggregate.avg_glucose_mgdl == 0.0
    assert aggregate.tir_target_pct == 0.0


def test_aggregate_day_full_summary() -> None:
    readings = [_r(0, 80), _r(5 * 60, 100), _r(10 * 60, 200), _r(15 * 60, 270)]
    aggregate = aggregate_day(dt.date(2026, 5, 1), readings)
    assert aggregate.reading_count == 4
    assert aggregate.avg_glucose_mgdl == round(sum(r.value_mgdl for r in readings) / 4, 1)
    assert aggregate.gmi_percent > 0
    assert aggregate.hyper_events == 1  # 270 only
    assert aggregate.hypo_events == 0


def test_aggregate_range_buckets_by_local_date() -> None:
    readings = [
        _r(0, 100, day=1),
        _r(5 * 60, 110, day=1),
        _r(0, 200, day=2),
    ]
    aggregates = aggregate_range(readings)
    assert set(aggregates.keys()) == {dt.date(2026, 5, 1), dt.date(2026, 5, 2)}
    assert aggregates[dt.date(2026, 5, 1)].reading_count == 2
    assert aggregates[dt.date(2026, 5, 2)].reading_count == 1


def test_aggregate_window_returns_none_when_no_usable_readings() -> None:
    assert aggregate_window([]) is None


def test_aggregate_window_aggregates_across_dates() -> None:
    readings = [_r(0, 100, day=1), _r(0, 200, day=2)]
    aggregate = aggregate_window(readings)
    assert aggregate is not None
    assert aggregate.reading_count == 2
    assert aggregate.avg_glucose_mgdl == 150.0
