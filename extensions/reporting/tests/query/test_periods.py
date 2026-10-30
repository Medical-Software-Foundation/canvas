# tests/query/test_periods.py
from __future__ import annotations

from datetime import date, datetime

from reporting.query.periods import PeriodSpec, compute_periods


def test_last_3_months_windows():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=False)
    periods = compute_periods(spec, anchor=date(2026, 6, 15))
    assert [p.label for p in periods] == ["Apr 2026", "May 2026", "Jun 2026"]
    jun = periods[-1]
    assert jun.start == datetime(2026, 6, 1, 0, 0, 0)
    assert jun.end == datetime(2026, 7, 1, 0, 0, 0)  # half-open [start, end)
    apr = periods[0]
    assert apr.start == datetime(2026, 4, 1, 0, 0, 0)
    assert apr.end == datetime(2026, 5, 1, 0, 0, 0)


def test_month_rollover_into_previous_year():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=False)
    periods = compute_periods(spec, anchor=date(2026, 1, 10))
    assert [p.label for p in periods] == ["Nov 2025", "Dec 2025", "Jan 2026"]


def test_rolling_12_months_overrides_count():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=True)
    periods = compute_periods(spec, anchor=date(2026, 6, 15))
    assert len(periods) == 12
    assert periods[0].label == "Jul 2025"
    assert periods[-1].label == "Jun 2026"


def test_quarter_windows():
    spec = PeriodSpec(granularity="quarter", count=2, include_rolling_12=False)
    periods = compute_periods(spec, anchor=date(2026, 5, 1))  # Q2 2026
    assert [p.label for p in periods] == ["Q1 2026", "Q2 2026"]
    assert periods[-1].start == datetime(2026, 4, 1)
    assert periods[-1].end == datetime(2026, 7, 1)


def test_week_windows_start_monday():
    spec = PeriodSpec(granularity="week", count=2, include_rolling_12=False)
    # 2026-06-15 is a Monday
    periods = compute_periods(spec, anchor=date(2026, 6, 17))  # Wed of that week
    assert periods[-1].start == datetime(2026, 6, 15)
    assert periods[-1].end == datetime(2026, 6, 22)
    assert periods[0].start == datetime(2026, 6, 8)


def test_invalid_granularity_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown granularity"):
        PeriodSpec(granularity="day", count=3, include_rolling_12=False)


def test_count_zero_raises():
    import pytest
    with pytest.raises(ValueError, match="count must be >= 1"):
        PeriodSpec(granularity="month", count=0, include_rolling_12=False)


def test_rolling_12_requires_month_granularity():
    import pytest
    with pytest.raises(ValueError, match="only valid with granularity='month'"):
        PeriodSpec(granularity="week", count=3, include_rolling_12=True)


def test_rolling_12_periods_are_contiguous():
    spec = PeriodSpec(granularity="month", count=3, include_rolling_12=True)
    periods = compute_periods(spec, anchor=date(2026, 6, 15))
    assert all(periods[i].end == periods[i + 1].start for i in range(len(periods) - 1))
