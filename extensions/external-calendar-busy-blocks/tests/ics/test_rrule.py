from datetime import datetime, timedelta, timezone

import pytest

from external_calendar_busy_blocks.ics.rrule import (
    RRule,
    parse_rrule,
    expand_rrule,
    RRuleUnsupported,
)


def test_parse_freq_weekly_byday() -> None:
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR;INTERVAL=2;COUNT=10")
    assert rule.freq == "WEEKLY"
    assert rule.interval == 2
    assert rule.byday == [(0, "MO"), (0, "WE"), (0, "FR")]
    assert rule.count == 10
    assert rule.until is None


def test_parse_until_parses_utc_datetime() -> None:
    rule = parse_rrule("FREQ=DAILY;UNTIL=20261231T235959Z")
    assert rule.until == datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def test_parse_rejects_unsupported_bysetpos() -> None:
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1")


def test_parse_rejects_unsupported_byweekno() -> None:
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=YEARLY;BYWEEKNO=20")


def test_expand_daily_with_count() -> None:
    rule = parse_rrule("FREQ=DAILY;COUNT=5")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 30, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    assert len(occurrences) == 5
    assert occurrences[0] == dtstart
    assert occurrences[4] == dtstart + timedelta(days=4)


def test_expand_weekly_byday_with_count() -> None:
    # 2026-06-01 is a Monday. FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4 should produce
    # MO 6/1, WE 6/3, MO 6/8, WE 6/10.
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    assert [o.date().day for o in occurrences] == [1, 3, 8, 10]


def test_expand_daily_until() -> None:
    rule = parse_rrule("FREQ=DAILY;UNTIL=20260605T000000Z")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    # UNTIL is inclusive but 6/5 00:00 < 6/5 14:00 -> last occurrence 6/4
    assert [o.date().day for o in occurrences] == [1, 2, 3, 4]


def test_expand_respects_window_end() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 5, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    assert len(occurrences) == 4  # 6/1, 6/2, 6/3, 6/4


def test_expand_respects_cap() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=10))
    assert len(occurrences) == 10


def test_expand_monthly_first_monday() -> None:
    rule = parse_rrule("FREQ=MONTHLY;BYDAY=1MO;COUNT=3")
    dtstart = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)  # 1st Monday of June
    window_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    # 1st Mondays: Jun 1 2026, Jul 6 2026, Aug 3 2026
    assert [(o.year, o.month, o.day) for o in occurrences] == [
        (2026, 6, 1), (2026, 7, 6), (2026, 8, 3),
    ]


def test_expand_monthly_bymonthday() -> None:
    rule = parse_rrule("FREQ=MONTHLY;BYMONTHDAY=15;COUNT=2")
    dtstart = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
    window_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    assert [(o.year, o.month, o.day) for o in occurrences] == [
        (2026, 6, 15), (2026, 7, 15),
    ]


def test_expand_yearly_bymonth_bymonthday() -> None:
    rule = parse_rrule("FREQ=YEARLY;BYMONTH=12;BYMONTHDAY=25;COUNT=2")
    dtstart = datetime(2026, 12, 25, 14, 0, tzinfo=timezone.utc)
    window_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    assert [(o.year, o.month, o.day) for o in occurrences] == [
        (2026, 12, 25), (2027, 12, 25),
    ]
