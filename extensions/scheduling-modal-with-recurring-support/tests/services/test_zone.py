from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scheduling_modal_with_recurring_support.services.zone import client_zone


def test_valid_iana_name_returns_zoneinfo() -> None:
    """Covers backlog item B1, the daylight saving shift.

    A valid IANA name resolves to a ZoneInfo rather than the fixed offset,
    so the caller gets an object whose offset is computed per date.
    """
    zone = client_zone("America/Los_Angeles", 420)
    assert isinstance(zone, ZoneInfo)


def test_named_zone_offset_differs_across_daylight_saving_change() -> None:
    """Covers backlog item B1, the daylight saving shift.

    America/Los_Angeles moves off daylight saving on 2026-11-01. A ZoneInfo
    reports a different UTC offset for a date before that change than for a
    date after it, which is exactly what a fixed offset read once at click
    time cannot do.
    """
    zone = client_zone("America/Los_Angeles", 420)

    before = datetime(2026, 10, 5, 10, 0, tzinfo=zone)
    after = datetime(2026, 11, 9, 10, 0, tzinfo=zone)

    assert before.utcoffset() != after.utcoffset()
    assert before.utcoffset() == timedelta(hours=-7)
    assert after.utcoffset() == timedelta(hours=-8)


def test_empty_name_falls_back_to_fixed_offset() -> None:
    """Covers backlog item B1, the daylight saving shift.

    No tz_name at all is the old behaviour, a browser that never sent one,
    or a caller from before this change. The fixed offset stands in.
    """
    zone = client_zone("", 240)
    assert zone == timezone(timedelta(minutes=-240))


def test_blank_name_falls_back_to_fixed_offset() -> None:
    """Covers backlog item B1, the daylight saving shift.

    A tz_name of only whitespace is treated the same as empty.
    """
    zone = client_zone("   ", 240)
    assert zone == timezone(timedelta(minutes=-240))


def test_bogus_name_falls_back_to_fixed_offset() -> None:
    """Covers backlog item B1, the daylight saving shift.

    A name this runtime cannot look up, ZoneInfoNotFoundError under the
    hood, falls back rather than raising, so a browser that sent a name
    Canvas cannot resolve still gets a usable zone.
    """
    zone = client_zone("Not/A_Real_Zone", 240)
    assert zone == timezone(timedelta(minutes=-240))


def test_malformed_name_falls_back_to_fixed_offset() -> None:
    """Covers backlog item B1, the daylight saving shift.

    A malformed name raises ValueError inside zoneinfo rather than
    KeyError, and that path also falls back instead of raising.
    """
    zone = client_zone("../../etc/passwd", 240)
    assert zone == timezone(timedelta(minutes=-240))
