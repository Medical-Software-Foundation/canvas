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
