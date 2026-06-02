import pytest

from external_calendar_busy_blocks.ics.parser import unfold_lines
from external_calendar_busy_blocks.ics.types import IcsParseError


def test_unfold_lines_no_folding() -> None:
    body = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    assert unfold_lines(body) == ["BEGIN:VCALENDAR", "VERSION:2.0", "END:VCALENDAR"]


def test_unfold_lines_folded_with_space() -> None:
    # RFC 5545 line fold: the CRLF + single WSP sequence is removed entirely.
    # Real feeds preserve a content space by putting it before the CRLF.
    body = b"DESCRIPTION:This is a long \r\n description that wraps\r\n"
    assert unfold_lines(body) == ["DESCRIPTION:This is a long description that wraps"]


def test_unfold_lines_folded_strips_continuation_wsp() -> None:
    # No content space on either side -> the two halves concatenate directly.
    body = b"DESCRIPTION:long\r\n word\r\n"
    assert unfold_lines(body) == ["DESCRIPTION:longword"]


def test_unfold_lines_folded_with_tab() -> None:
    # Tab continuation is also stripped entirely
    body = b"SUMMARY:Multi\r\n\tline\r\n"
    assert unfold_lines(body) == ["SUMMARY:Multiline"]


def test_unfold_lines_accepts_lf_only() -> None:
    body = b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"
    assert unfold_lines(body) == ["BEGIN:VCALENDAR", "END:VCALENDAR"]


def test_unfold_lines_strips_blank_lines() -> None:
    body = b"BEGIN:VCALENDAR\r\n\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
    assert unfold_lines(body) == ["BEGIN:VCALENDAR", "VERSION:2.0", "END:VCALENDAR"]


def test_unfold_lines_rejects_non_utf8() -> None:
    with pytest.raises(IcsParseError):
        unfold_lines(b"\xff\xfeBEGIN:VCALENDAR\r\n")


from external_calendar_busy_blocks.ics.parser import (
    parse_property_line,
    extract_vevents,
)


def test_parse_property_simple() -> None:
    name, params, value = parse_property_line("SUMMARY:Hello world")
    assert name == "SUMMARY"
    assert params == {}
    assert value == "Hello world"


def test_parse_property_with_one_param() -> None:
    name, params, value = parse_property_line(
        "DTSTART;TZID=America/New_York:20260601T090000"
    )
    assert name == "DTSTART"
    assert params == {"TZID": "America/New_York"}
    assert value == "20260601T090000"


def test_parse_property_with_multiple_params() -> None:
    name, params, value = parse_property_line(
        "ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED:mailto:x@y.com"
    )
    assert name == "ATTENDEE"
    assert params == {"ROLE": "REQ-PARTICIPANT", "PARTSTAT": "ACCEPTED"}
    assert value == "mailto:x@y.com"


def test_parse_property_value_contains_colon() -> None:
    name, params, value = parse_property_line("ORGANIZER:mailto:foo@bar.com")
    assert name == "ORGANIZER"
    assert value == "mailto:foo@bar.com"


def test_extract_vevents_groups_lines() -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VEVENT",
        "UID:a@x",
        "SUMMARY:A",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:b@x",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    events = extract_vevents(lines)
    assert len(events) == 2
    assert events[0][0] == ("UID", {}, "a@x")
    assert events[1][0] == ("UID", {}, "b@x")


def test_extract_vevents_ignores_other_components() -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "BEGIN:VTIMEZONE",
        "TZID:UTC",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        "UID:a@x",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    assert len(extract_vevents(lines)) == 1


def test_extract_vevents_raises_on_missing_vcalendar() -> None:
    with pytest.raises(IcsParseError):
        extract_vevents(["BEGIN:VEVENT", "UID:x", "END:VEVENT"])


from datetime import datetime, timezone

from external_calendar_busy_blocks.ics.parser import parse_ics


def test_parse_simple_confirmed(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("simple_confirmed.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert len(events) == 1
    e = events[0]
    assert e.uid == "simple-1@test"
    assert e.recurrence_id is None
    assert e.starts_at == datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    assert e.ends_at == datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)
    assert e.is_all_day is False
    assert e.sequence == 0


def test_parse_skips_transparent(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("transparent_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert events == []


def test_parse_skips_tentative(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("tentative_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert events == []


def test_parse_skips_cancelled(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("cancelled_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert events == []


def test_parse_all_day(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("all_day_event.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert len(events) == 1
    assert events[0].is_all_day is True
    assert events[0].starts_at == datetime(2026, 6, 15, tzinfo=timezone.utc)


def test_parse_multi_timezone(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("multi_timezone.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    assert len(events) == 2
    # PST 09:00 -> UTC 16:00 (PDT, UTC-7 in June)
    pst = next(e for e in events if e.uid == "tz-pst@test")
    assert pst.starts_at == datetime(2026, 6, 1, 16, 0, tzinfo=timezone.utc)
    utc = next(e for e in events if e.uid == "tz-utc@test")
    assert utc.starts_at == datetime(2026, 6, 1, 20, 0, tzinfo=timezone.utc)


def test_parse_floating_uses_x_wr_timezone(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("floating_time.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # NY 09:00 (EDT, UTC-4) -> 13:00 UTC
    assert events[0].starts_at == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)


def test_parse_malformed_raises(ics_fixture) -> None:
    with pytest.raises(IcsParseError):
        parse_ics(
            ics_fixture("malformed.ics"),
            now=datetime(2026, 6, 1, tzinfo=timezone.utc),
            lookahead_days=90,
        )


def test_parse_weekly_recurring(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("weekly_recurring.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # MO 6/1, WE 6/3, MO 6/8, WE 6/10
    assert len(events) == 4
    days = sorted(e.starts_at.day for e in events)
    assert days == [1, 3, 8, 10]
    assert all(e.uid == "weekly-1@test" for e in events)


def test_parse_rrule_with_exdate(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("rrule_with_exdate.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # 4 Mondays: 6/1, 6/8, 6/15, 6/22. EXDATE excludes 6/15.
    days = sorted(e.starts_at.day for e in events)
    assert days == [1, 8, 22]


def test_parse_recurrence_id_override(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("recurrence_id_override.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=90,
    )
    # 3 occurrences: 6/1, 6/8 (overridden), 6/15
    by_day = {e.starts_at.day: e for e in events}
    assert set(by_day.keys()) == {1, 8, 15}
    # The 6/8 instance was overridden to start at 16:00 instead of 14:00
    assert by_day[8].starts_at == datetime(2026, 6, 8, 16, 0, tzinfo=timezone.utc)
    assert by_day[8].recurrence_id == "20260608T140000Z"


def test_parse_oversized_rrule_capped_at_1000(ics_fixture) -> None:
    events = parse_ics(
        ics_fixture("oversized_rrule.ics"),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        lookahead_days=3650,  # huge window to remove that constraint
    )
    assert len(events) == 1000
