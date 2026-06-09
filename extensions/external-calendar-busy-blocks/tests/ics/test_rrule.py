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


def test_expand_daily_historical_dtstart_still_yields_window() -> None:
    # Regression: a daily event whose DTSTART is years before the window must
    # still yield the in-window occurrences. The cap bounds YIELDED events, not
    # candidates considered — otherwise the cap is burned on pre-window days and
    # zero events reach the schedule.
    rule = parse_rrule("FREQ=DAILY")
    dtstart = datetime(2022, 1, 1, 14, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 8, tzinfo=timezone.utc)
    occurrences = list(
        expand_rrule(rule, dtstart, window_start, window_end, cap=1000)
    )
    # 6/1 14:00 .. 6/7 14:00 -> 7 occurrences inside the window.
    assert [o.day for o in occurrences] == [1, 2, 3, 4, 5, 6, 7]


def test_expand_weekly_historical_dtstart_still_yields_window() -> None:
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR")
    dtstart = datetime(2022, 1, 3, 9, 0, tzinfo=timezone.utc)  # a Monday in 2022
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)   # Monday 2026-06-01
    window_end = datetime(2026, 6, 8, tzinfo=timezone.utc)
    occurrences = list(
        expand_rrule(rule, dtstart, window_start, window_end, cap=1000)
    )
    # Mon 6/1, Wed 6/3, Fri 6/5 of 2026.
    assert [o.day for o in occurrences] == [1, 3, 5]


def test_expand_cap_limits_yielded_not_candidates() -> None:
    # With a historical DTSTART and a small cap, the cap must limit how many
    # in-window events are yielded, not be consumed by pre-window candidates.
    rule = parse_rrule("FREQ=DAILY")
    dtstart = datetime(2020, 1, 1, 9, 0, tzinfo=timezone.utc)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=5))
    assert len(occurrences) == 5
    assert occurrences[0].day == 1 and occurrences[0].month == 6


def test_expand_invalid_bymonth_terminates() -> None:
    # A BYMONTH that never matches must not loop forever; it should simply
    # yield nothing and return.
    rule = parse_rrule("FREQ=MONTHLY;BYMONTH=13")
    dtstart = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    window_end = datetime(2027, 6, 1, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, dtstart, window_end, cap=1000))
    assert occurrences == []


def test_expand_weekly_uses_local_weekday_not_utc() -> None:
    # expand_rrule must evaluate BYDAY against the timezone of the dtstart it is
    # given. Feed a Chicago-local Tuesday 19:00 and assert occurrences stay on
    # local Tuesdays (which are Wednesday 00:00 in UTC).
    from zoneinfo import ZoneInfo

    chicago = ZoneInfo("America/Chicago")
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=TU")
    dtstart = datetime(2026, 6, 2, 19, 0, tzinfo=chicago)
    window_start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    window_end = datetime(2026, 6, 23, tzinfo=timezone.utc)
    occurrences = list(expand_rrule(rule, dtstart, window_start, window_end, cap=1000))
    locals_ = [o.astimezone(chicago) for o in occurrences]
    assert all(d.weekday() == 1 and d.hour == 19 for d in locals_), locals_
    assert [d.date().isoformat() for d in locals_] == [
        "2026-06-02", "2026-06-09", "2026-06-16",
    ]


def test_parse_rrule_rejects_zero_interval() -> None:
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=DAILY;INTERVAL=0")


def test_parse_rrule_rejects_negative_count() -> None:
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=DAILY;COUNT=0")


def test_expand_monthly_day31_skips_short_months() -> None:
    # FREQ=MONTHLY on day 31 (no BY*) must skip months without a 31st,
    # not clamp to the last day (RFC 5545 §3.3.10).
    rule = parse_rrule("FREQ=MONTHLY")
    dtstart = datetime(2026, 1, 31, 14, 0, tzinfo=timezone.utc)
    occ = list(expand_rrule(
        rule, dtstart,
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        cap=1000,
    ))
    assert [(o.month, o.day) for o in occ] == [(1, 31), (3, 31), (5, 31)]


def test_expand_yearly_feb29_skips_non_leap_years() -> None:
    rule = parse_rrule("FREQ=YEARLY")
    dtstart = datetime(2024, 2, 29, 14, 0, tzinfo=timezone.utc)
    occ = list(expand_rrule(
        rule, dtstart,
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2030, 1, 1, tzinfo=timezone.utc),
        cap=1000,
    ))
    # Only leap years 2024 and 2028; no spurious Feb 28 in 2025/26/27/29.
    assert [(o.year, o.month, o.day) for o in occ] == [(2024, 2, 29), (2028, 2, 29)]


def test_parse_rrule_rejects_non_mo_wkst_only_when_significant() -> None:
    # WKST changes the expansion only for WEEKLY + INTERVAL>1 + multiple BYDAY.
    with pytest.raises(RRuleUnsupported):
        parse_rrule("FREQ=WEEKLY;BYDAY=SU,SA;INTERVAL=2;WKST=SU")


def test_parse_rrule_ignores_non_mo_wkst_when_irrelevant() -> None:
    # WKST=SU is Google's default and has no effect on these expansions, so the
    # rules must be accepted (previously every one of these was dropped).
    # Weekly, every week (INTERVAL defaults to 1):
    assert parse_rrule("FREQ=WEEKLY;BYDAY=TU;WKST=SU").freq == "WEEKLY"
    # Weekly, single weekday, INTERVAL>1 (week boundary is irrelevant):
    assert parse_rrule("FREQ=WEEKLY;BYDAY=WE;INTERVAL=2;WKST=SU").interval == 2
    # Non-weekly frequencies — WKST never applies:
    assert parse_rrule("FREQ=MONTHLY;BYDAY=2MO;WKST=SU").freq == "MONTHLY"
    assert parse_rrule("FREQ=DAILY;INTERVAL=3;WKST=SU").freq == "DAILY"


def test_parse_rrule_accepts_default_mo_wkst() -> None:
    # WKST=MO is the default our expander already assumes; it must NOT be
    # dropped (that would lose legitimate recurring events).
    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO;WKST=MO")
    assert rule.freq == "WEEKLY"
