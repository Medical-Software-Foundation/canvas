"""Tests for billing_dashboard.data.windows — calendar + trailing window helpers."""

import arrow
import pytest

from billing_dashboard.data import windows


@pytest.fixture
def fixed_now() -> arrow.Arrow:
    # Wednesday, 2026-04-15 14:30:00 UTC
    return arrow.get(2026, 4, 15, 14, 30, 0)


class TestThisMonthRange:
    def test_starts_at_first_of_current_month_midnight_utc(self, fixed_now: arrow.Arrow) -> None:
        start, _ = windows.this_month_range(now=fixed_now)
        assert start == arrow.get(2026, 4, 1, 0, 0, 0)

    def test_ends_at_now(self, fixed_now: arrow.Arrow) -> None:
        _, end = windows.this_month_range(now=fixed_now)
        assert end == fixed_now


class TestLastMonthRange:
    def test_spans_full_previous_month(self, fixed_now: arrow.Arrow) -> None:
        start, end = windows.last_month_range(now=fixed_now)
        assert start == arrow.get(2026, 3, 1, 0, 0, 0)
        assert end == arrow.get(2026, 4, 1, 0, 0, 0)

    def test_january_rolls_back_to_december(self) -> None:
        now = arrow.get(2026, 1, 10, 0, 0, 0)
        start, end = windows.last_month_range(now=now)
        assert start == arrow.get(2025, 12, 1, 0, 0, 0)
        assert end == arrow.get(2026, 1, 1, 0, 0, 0)


class TestNextMonthRange:
    def test_spans_full_next_month(self, fixed_now: arrow.Arrow) -> None:
        start, end = windows.next_month_range(now=fixed_now)
        assert start == arrow.get(2026, 5, 1, 0, 0, 0)
        assert end == arrow.get(2026, 6, 1, 0, 0, 0)

    def test_december_rolls_forward_to_january(self) -> None:
        now = arrow.get(2026, 12, 10, 0, 0, 0)
        start, end = windows.next_month_range(now=now)
        assert start == arrow.get(2027, 1, 1, 0, 0, 0)
        assert end == arrow.get(2027, 2, 1, 0, 0, 0)


class TestTrailing30DaysRange:
    def test_ends_at_now(self, fixed_now: arrow.Arrow) -> None:
        _, end = windows.trailing_30_days_range(now=fixed_now)
        assert end == fixed_now

    def test_starts_30_days_before_now(self, fixed_now: arrow.Arrow) -> None:
        start, _ = windows.trailing_30_days_range(now=fixed_now)
        assert start == fixed_now.shift(days=-30)


class TestTrailing90DaysRange:
    def test_starts_90_days_before_now(self, fixed_now: arrow.Arrow) -> None:
        start, end = windows.trailing_90_days_range(now=fixed_now)
        assert end == fixed_now
        assert start == fixed_now.shift(days=-90)


class TestTrailing12MonthsRange:
    def test_ends_at_first_of_this_month(self, fixed_now: arrow.Arrow) -> None:
        _, end = windows.trailing_12_months_range(now=fixed_now)
        assert end == arrow.get(2026, 4, 1, 0, 0, 0)

    def test_starts_at_first_of_month_12_months_before_this_month(self, fixed_now: arrow.Arrow) -> None:
        start, _ = windows.trailing_12_months_range(now=fixed_now)
        assert start == arrow.get(2025, 4, 1, 0, 0, 0)


class TestDefaultNowIsUtcnow:
    def test_this_month_range_uses_arrow_utcnow_when_now_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = arrow.get(2026, 7, 15, 10, 0, 0)
        monkeypatch.setattr(arrow, "utcnow", lambda: sentinel)
        start, end = windows.this_month_range()
        assert start == arrow.get(2026, 7, 1, 0, 0, 0)
        assert end == sentinel
