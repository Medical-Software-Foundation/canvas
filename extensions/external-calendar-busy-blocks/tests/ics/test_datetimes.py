from datetime import datetime, timezone

import pytest

from external_calendar_busy_blocks.ics.datetimes import (
    parse_ics_datetime,
    DateValue,
)
from external_calendar_busy_blocks.ics.types import IcsParseError


def test_parse_utc_zulu() -> None:
    result = parse_ics_datetime("20260601T140000Z", params={}, default_tz="UTC")
    expected = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    assert result.moment == expected
    assert result.is_all_day is False
    # For a Zulu value the evaluation zone is UTC, so local == moment.
    assert result.local == expected


def test_parse_tzid_converts_to_utc() -> None:
    # 09:00 in America/New_York on 2026-06-01 (EDT, UTC-4) == 13:00 UTC
    result = parse_ics_datetime(
        "20260601T090000",
        params={"TZID": "America/New_York"},
        default_tz="UTC",
    )
    assert result.moment == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
    assert result.is_all_day is False
    # local preserves the source wall-clock time and zone for RRULE math.
    assert result.local.hour == 9
    assert result.local.utcoffset().total_seconds() == -4 * 3600
    # Same absolute instant either way.
    assert result.local == result.moment


def test_parse_tzid_local_preserves_calendar_day_across_utc_midnight() -> None:
    # Tue 19:00 America/Chicago is Wed 00:00 UTC. `local` must still read as
    # Tuesday so RRULE BYDAY math lands on the right day.
    result = parse_ics_datetime(
        "20260602T190000",
        params={"TZID": "America/Chicago"},
        default_tz="UTC",
    )
    assert result.moment == datetime(2026, 6, 3, 0, 0, tzinfo=timezone.utc)
    assert result.local.weekday() == 1  # Tuesday (UTC moment would be Wednesday=2)
    assert result.local.hour == 19


def test_parse_floating_uses_default_tz() -> None:
    result = parse_ics_datetime(
        "20260601T090000",
        params={},
        default_tz="America/New_York",
    )
    assert result.moment == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)


def test_parse_date_only_all_day() -> None:
    result = parse_ics_datetime("20260601", params={"VALUE": "DATE"}, default_tz="UTC")
    assert result.is_all_day is True
    assert result.moment == datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)


def test_parse_unknown_tzid_raises() -> None:
    with pytest.raises(IcsParseError):
        parse_ics_datetime(
            "20260601T090000",
            params={"TZID": "Bogus/Made_Up"},
            default_tz="UTC",
        )


def test_parse_malformed_value_raises() -> None:
    with pytest.raises(IcsParseError):
        parse_ics_datetime("not-a-date", params={}, default_tz="UTC")
