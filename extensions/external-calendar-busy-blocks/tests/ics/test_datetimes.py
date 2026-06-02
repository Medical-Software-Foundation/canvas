from datetime import datetime, timezone

import pytest

from external_calendar_busy_blocks.ics.datetimes import (
    parse_ics_datetime,
    DateValue,
)
from external_calendar_busy_blocks.ics.types import IcsParseError


def test_parse_utc_zulu() -> None:
    result = parse_ics_datetime("20260601T140000Z", params={}, default_tz="UTC")
    assert result == DateValue(
        moment=datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc),
        is_all_day=False,
    )


def test_parse_tzid_converts_to_utc() -> None:
    # 09:00 in America/New_York on 2026-06-01 (EDT, UTC-4) == 13:00 UTC
    result = parse_ics_datetime(
        "20260601T090000",
        params={"TZID": "America/New_York"},
        default_tz="UTC",
    )
    assert result.moment == datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
    assert result.is_all_day is False


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
