from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta

from external_calendar_busy_blocks.ics.types import IcsParseError


def _last_day_of_month(year: int, month: int) -> int:
    """Return the last day-of-month for the given year and month."""
    if month == 12:
        next_first = datetime(year + 1, 1, 1)
    else:
        next_first = datetime(year, month + 1, 1)
    return (next_first - timedelta(days=1)).day


class RRuleUnsupported(Exception):
    """Raised when an RRULE uses a feature this plugin does not support."""


SUPPORTED_FREQS = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
UNSUPPORTED_PARTS = {"BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND"}

WEEKDAY_TO_NUM = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


@dataclass
class RRule:
    freq: str
    interval: int = 1
    count: int | None = None
    until: datetime | None = None
    byday: list[tuple[int, str]] = field(default_factory=list)  # [(0,"MO"), ...]; first int is positional (0 = any)
    bymonthday: list[int] = field(default_factory=list)
    bymonth: list[int] = field(default_factory=list)


def parse_rrule(value: str) -> RRule:
    """Parse an RRULE property value into an RRule dataclass.

    Raises RRuleUnsupported for unsupported parts (BYSETPOS, BYWEEKNO, etc.)
    and IcsParseError for malformed values.
    """
    parts = {p.split("=", 1)[0].upper(): p.split("=", 1)[1] for p in value.split(";") if "=" in p}

    for k in parts:
        if k in UNSUPPORTED_PARTS:
            raise RRuleUnsupported(f"RRULE uses unsupported part {k}")

    freq = parts.get("FREQ", "").upper()
    if freq not in SUPPORTED_FREQS:
        raise RRuleUnsupported(f"RRULE FREQ={freq!r} is not supported")

    rule = RRule(freq=freq)

    if "INTERVAL" in parts:
        try:
            rule.interval = int(parts["INTERVAL"])
        except ValueError as exc:
            raise IcsParseError(f"INTERVAL is not an integer: {parts['INTERVAL']!r}") from exc

    if "COUNT" in parts:
        try:
            rule.count = int(parts["COUNT"])
        except ValueError as exc:
            raise IcsParseError(f"COUNT is not an integer: {parts['COUNT']!r}") from exc

    if "UNTIL" in parts:
        u = parts["UNTIL"]
        if u.endswith("Z"):
            u = u[:-1]
        if len(u) == 8 and u.isdigit():
            rule.until = datetime(int(u[0:4]), int(u[4:6]), int(u[6:8]), tzinfo=timezone.utc)
        elif len(u) == 15 and u[8] == "T":
            rule.until = datetime(
                int(u[0:4]), int(u[4:6]), int(u[6:8]),
                int(u[9:11]), int(u[11:13]), int(u[13:15]),
                tzinfo=timezone.utc,
            )
        else:
            raise IcsParseError(f"malformed UNTIL: {parts['UNTIL']!r}")

    if "BYDAY" in parts:
        for tok in parts["BYDAY"].split(","):
            tok = tok.strip().upper()
            i = 0
            while i < len(tok) and (tok[i].isdigit() or tok[i] in ("+", "-")):
                i += 1
            pos = int(tok[:i]) if i > 0 else 0
            day = tok[i:]
            if day not in WEEKDAY_TO_NUM:
                raise IcsParseError(f"invalid BYDAY weekday: {tok!r}")
            rule.byday.append((pos, day))

    if "BYMONTHDAY" in parts:
        try:
            rule.bymonthday = [int(x) for x in parts["BYMONTHDAY"].split(",")]
        except ValueError as exc:
            raise IcsParseError(f"invalid BYMONTHDAY: {parts['BYMONTHDAY']!r}") from exc

    if "BYMONTH" in parts:
        try:
            rule.bymonth = [int(x) for x in parts["BYMONTH"].split(",")]
        except ValueError as exc:
            raise IcsParseError(f"invalid BYMONTH: {parts['BYMONTH']!r}") from exc

    return rule


def expand_rrule(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
):
    """Yield occurrences of dtstart within [window_start, window_end).

    Always stops at min(rule.count, cap, end-of-window, rule.until).
    COUNT is consumed absolutely (per RFC 5545): occurrences outside the
    window still tick the count even if not yielded.
    """
    if rule.freq == "DAILY":
        yield from _expand_daily(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "WEEKLY":
        yield from _expand_weekly(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "MONTHLY":
        yield from _expand_monthly(rule, dtstart, window_start, window_end, cap)
    elif rule.freq == "YEARLY":
        yield from _expand_yearly(rule, dtstart, window_start, window_end, cap)


def _expand_daily(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
):
    cur = dtstart
    produced = 0
    while produced < cap:
        if rule.count is not None and produced >= rule.count:
            return
        if rule.until is not None and cur > rule.until:
            return
        if cur >= window_end:
            return
        if cur >= window_start:
            yield cur
        produced += 1
        cur = cur + timedelta(days=rule.interval)


def _expand_weekly(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
):
    # If no BYDAY, the rule recurs only on the DTSTART weekday.
    weekdays = [WEEKDAY_TO_NUM[d] for _, d in rule.byday] if rule.byday else [dtstart.weekday()]
    weekdays = sorted(set(weekdays))

    # Anchor to the Monday of the dtstart week (WKST default MO).
    week_start = dtstart - timedelta(days=dtstart.weekday())
    week_start = week_start.replace(
        hour=dtstart.hour,
        minute=dtstart.minute,
        second=dtstart.second,
        microsecond=0,
    )

    produced = 0
    week_no = 0
    while produced < cap:
        for wd in weekdays:
            moment = week_start + timedelta(weeks=week_no, days=wd)
            if moment < dtstart:
                # Pre-DTSTART candidates are not occurrences; don't tick COUNT.
                continue
            if rule.count is not None and produced >= rule.count:
                return
            if rule.until is not None and moment > rule.until:
                return
            if moment >= window_end:
                return
            if moment >= window_start:
                yield moment
            produced += 1
            if produced >= cap:
                return
        week_no += rule.interval
        next_week = week_start + timedelta(weeks=week_no)
        if next_week >= window_end:
            return


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> int | None:
    """Return the day-of-month for the Nth (1-based) weekday in (year, month)."""
    last_day = _last_day_of_month(year, month)
    if n > 0:
        first_match = ((weekday - datetime(year, month, 1).weekday()) % 7) + 1
        day = first_match + 7 * (n - 1)
        return day if day <= last_day else None
    if n < 0:
        last_match = last_day - ((datetime(year, month, last_day).weekday() - weekday) % 7)
        day = last_match - 7 * (-n - 1)
        return day if day >= 1 else None
    return None


def _candidate_days_in_month(rule: RRule, year: int, month: int, dtstart: datetime) -> list[int]:
    days: set[int] = set()
    if rule.byday:
        for pos, day in rule.byday:
            weekday = WEEKDAY_TO_NUM[day]
            if pos == 0:
                last = _last_day_of_month(year, month)
                for d in range(1, last + 1):
                    if datetime(year, month, d).weekday() == weekday:
                        days.add(d)
            else:
                d = _nth_weekday_of_month(year, month, weekday, pos)
                if d is not None:
                    days.add(d)
    if rule.bymonthday:
        last = _last_day_of_month(year, month)
        for d in rule.bymonthday:
            if d > 0 and d <= last:
                days.add(d)
            elif d < 0 and (last + d + 1) >= 1:
                days.add(last + d + 1)
    if not rule.byday and not rule.bymonthday:
        last = _last_day_of_month(year, month)
        days.add(dtstart.day if dtstart.day <= last else last)
    return sorted(days)


def _next_month(year: int, month: int, interval: int) -> tuple[int, int]:
    new = datetime(year, month, 1) + relativedelta(months=interval)
    return new.year, new.month


def _expand_monthly(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
):
    cursor_year, cursor_month = dtstart.year, dtstart.month
    produced = 0
    while produced < cap:
        if rule.bymonth and cursor_month not in rule.bymonth:
            cursor_year, cursor_month = _next_month(cursor_year, cursor_month, rule.interval)
            continue
        for d in _candidate_days_in_month(rule, cursor_year, cursor_month, dtstart):
            moment = datetime(
                cursor_year, cursor_month, d,
                dtstart.hour, dtstart.minute, dtstart.second,
                tzinfo=dtstart.tzinfo,
            )
            if moment < dtstart:
                continue
            if rule.count is not None and produced >= rule.count:
                return
            if rule.until is not None and moment > rule.until:
                return
            if moment >= window_end:
                return
            if moment >= window_start:
                yield moment
            produced += 1
            if produced >= cap:
                return
        cursor_year, cursor_month = _next_month(cursor_year, cursor_month, rule.interval)
        if datetime(cursor_year, cursor_month, 1, tzinfo=dtstart.tzinfo) >= window_end:
            return


def _expand_yearly(
    rule: RRule,
    dtstart: datetime,
    window_start: datetime,
    window_end: datetime,
    cap: int,
):
    cursor_year = dtstart.year
    produced = 0
    while produced < cap:
        months = rule.bymonth if rule.bymonth else [dtstart.month]
        for m in sorted(set(months)):
            days = _candidate_days_in_month(rule, cursor_year, m, dtstart) or [dtstart.day]
            for d in days:
                try:
                    moment = datetime(
                        cursor_year, m, d,
                        dtstart.hour, dtstart.minute, dtstart.second,
                        tzinfo=dtstart.tzinfo,
                    )
                except ValueError:
                    continue
                if moment < dtstart:
                    continue
                if rule.count is not None and produced >= rule.count:
                    return
                if rule.until is not None and moment > rule.until:
                    return
                if moment >= window_end:
                    return
                if moment >= window_start:
                    yield moment
                produced += 1
                if produced >= cap:
                    return
        cursor_year += rule.interval
        if datetime(cursor_year, 1, 1, tzinfo=dtstart.tzinfo) >= window_end:
            return
