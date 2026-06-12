"""Calendar and trailing time-window helpers for billing dashboard queries.

All windows are half-open intervals (start is inclusive, end is exclusive for
month-aligned windows; trailing-day windows use (now - Nd, now]).
All times are UTC.
"""

from __future__ import annotations

import arrow


def _utcnow_if_none(now: arrow.Arrow | None) -> arrow.Arrow:
    return now if now is not None else arrow.utcnow()


def _first_of_month(dt: arrow.Arrow) -> arrow.Arrow:
    return dt.floor("month")


def this_month_range(now: arrow.Arrow | None = None) -> tuple[arrow.Arrow, arrow.Arrow]:
    """[first of this month 00:00 UTC, now]."""
    now = _utcnow_if_none(now)
    return _first_of_month(now), now


def last_month_range(now: arrow.Arrow | None = None) -> tuple[arrow.Arrow, arrow.Arrow]:
    """[first of last month 00:00 UTC, first of this month 00:00 UTC]."""
    now = _utcnow_if_none(now)
    this_month_start = _first_of_month(now)
    last_month_start = _first_of_month(now.shift(months=-1))
    return last_month_start, this_month_start


def next_month_range(now: arrow.Arrow | None = None) -> tuple[arrow.Arrow, arrow.Arrow]:
    """[first of next month 00:00 UTC, first of month-after-next 00:00 UTC]."""
    now = _utcnow_if_none(now)
    next_month_start = _first_of_month(now.shift(months=1))
    month_after = _first_of_month(now.shift(months=2))
    return next_month_start, month_after


def trailing_30_days_range(now: arrow.Arrow | None = None) -> tuple[arrow.Arrow, arrow.Arrow]:
    """(now - 30 days, now]."""
    now = _utcnow_if_none(now)
    return now.shift(days=-30), now


def trailing_90_days_range(now: arrow.Arrow | None = None) -> tuple[arrow.Arrow, arrow.Arrow]:
    """(now - 90 days, now]."""
    now = _utcnow_if_none(now)
    return now.shift(days=-90), now


def trailing_12_months_range(now: arrow.Arrow | None = None) -> tuple[arrow.Arrow, arrow.Arrow]:
    """[first of (now - 12 months) 00:00 UTC, first of this month 00:00 UTC]."""
    now = _utcnow_if_none(now)
    start = _first_of_month(now.shift(months=-12))
    end = _first_of_month(now)
    return start, end
