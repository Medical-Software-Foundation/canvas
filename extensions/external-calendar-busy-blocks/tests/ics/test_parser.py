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
