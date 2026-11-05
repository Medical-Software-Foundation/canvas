"""Period window math for time comparison. Pure Python — no DB truncation."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GRANULARITIES = ("month", "week", "quarter")


@dataclass(frozen=True)
class PeriodSpec:
    granularity: str           # "month" | "week" | "quarter"
    count: int                 # number of recent periods (e.g. 3)
    include_rolling_12: bool    # if True (month granularity only), return 12 monthly periods regardless of count

    def __post_init__(self) -> None:
        if self.granularity not in GRANULARITIES:
            raise ValueError(f"Unknown granularity: {self.granularity}")
        if self.count < 1:
            raise ValueError("count must be >= 1")
        if self.include_rolling_12 and self.granularity != "month":
            raise ValueError("include_rolling_12 is only valid with granularity='month'")


@dataclass(frozen=True)
class Period:
    label: str
    start: datetime    # inclusive
    end: datetime      # exclusive (half-open [start, end))


def _month_start(d: date) -> datetime:
    return datetime(d.year, d.month, 1)


def _add_months(dt: datetime, months: int) -> datetime:
    total = (dt.year * 12 + (dt.month - 1)) + months
    return datetime(total // 12, total % 12 + 1, 1)


def _month_period(anchor_month_start: datetime, offset_from_newest: int) -> Period:
    start = _add_months(anchor_month_start, -offset_from_newest)
    end = _add_months(start, 1)
    return Period(label=f"{_MONTHS[start.month - 1]} {start.year}", start=start, end=end)


def _quarter_period(anchor: date, offset_from_newest: int) -> Period:
    q_index = (anchor.year * 4) + ((anchor.month - 1) // 3) - offset_from_newest
    year, q = divmod(q_index, 4)
    start = datetime(year, q * 3 + 1, 1)
    end = _add_months(start, 3)
    return Period(label=f"Q{q + 1} {year}", start=start, end=end)


def _week_period(anchor: date, offset_from_newest: int) -> Period:
    monday = anchor - timedelta(days=anchor.weekday())
    start_date = monday - timedelta(weeks=offset_from_newest)
    start = datetime(start_date.year, start_date.month, start_date.day)
    end = start + timedelta(weeks=1)
    return Period(label=f"Week of {start.date().isoformat()}", start=start, end=end)


def compute_periods(spec: PeriodSpec, anchor: date) -> list[Period]:
    """Return periods oldest -> newest, newest containing `anchor`."""
    if spec.include_rolling_12:
        base = _month_start(anchor)
        return [_month_period(base, offset) for offset in range(11, -1, -1)]

    n = spec.count
    if spec.granularity == "month":
        base = _month_start(anchor)
        return [_month_period(base, offset) for offset in range(n - 1, -1, -1)]
    if spec.granularity == "quarter":
        return [_quarter_period(anchor, offset) for offset in range(n - 1, -1, -1)]
    return [_week_period(anchor, offset) for offset in range(n - 1, -1, -1)]
