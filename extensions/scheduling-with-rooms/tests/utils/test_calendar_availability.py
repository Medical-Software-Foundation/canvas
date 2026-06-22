"""Tests for calendar_availability.py."""

import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scheduling_with_rooms.utils.calendar_availability import (
    _DAY_MAP,
    _event_window_on_date,
    _parse_rrule,
    _resolve_calendars,
    _resolve_staff,
    _staff_calendars,
    event_occurs_on_date,
    get_availability_windows,
    get_blocking_calendar_events,
    get_location_timezone,
    get_providers_for_location,
    parse_calendar_title,
)


# parse_calendar_title -------------------------------------------------

def test_parse_calendar_title_three_parts():
    name, ctype, loc = parse_calendar_title("Christopher Taylor: Clinic: Florida")
    assert name == "Christopher Taylor"
    assert ctype == "Clinic"
    assert loc == "Florida"


def test_parse_calendar_title_two_parts():
    name, ctype, loc = parse_calendar_title("Richard Wilson: Clinic")
    assert name == "Richard Wilson"
    assert ctype == "Clinic"
    assert loc is None


def test_parse_calendar_title_one_part():
    name, ctype, loc = parse_calendar_title("Just A Name")
    assert name == "Just A Name"
    assert ctype == ""
    assert loc is None


def test_parse_calendar_title_location_with_colon():
    name, ctype, loc = parse_calendar_title("Dr. X: Clinic: Loc:Sub")
    assert loc == "Loc:Sub"


# _parse_rrule -----------------------------------------------------------

def test_parse_rrule_strips_prefix():
    parsed = _parse_rrule("RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE")
    assert parsed == {"FREQ": "WEEKLY", "INTERVAL": "2", "BYDAY": "MO,WE"}


def test_parse_rrule_without_prefix():
    parsed = _parse_rrule("FREQ=DAILY")
    assert parsed == {"FREQ": "DAILY"}


def test_parse_rrule_empty_parts_skipped():
    parsed = _parse_rrule("FREQ=DAILY;;BAD")
    assert parsed == {"FREQ": "DAILY"}


# event_occurs_on_date ---------------------------------------------------

def test_event_occurs_on_date_no_starts_at():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = None
    assert event_occurs_on_date(event, datetime.date(2026, 5, 7)) is False


def test_event_occurs_on_date_no_recurrence_match():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0)
    event.recurrence = None
    assert event_occurs_on_date(event, datetime.date(2026, 5, 7)) is True


def test_event_occurs_on_date_no_recurrence_no_match():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0)
    event.recurrence = None
    assert event_occurs_on_date(event, datetime.date(2026, 5, 8)) is False


def test_event_occurs_on_date_target_before_start():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0)
    event.recurrence = "FREQ=DAILY"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 1)) is False


def test_event_occurs_on_date_until_passed():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY;UNTIL=20260505T235959"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 10)) is False


def test_event_occurs_on_date_until_invalid_continues():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY;UNTIL=BAD"
    # Should still match daily.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 10)) is True


def test_event_occurs_on_date_daily_interval_one():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is True


def test_event_occurs_on_date_daily_interval_three_match():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY;INTERVAL=3"
    # Days 1, 4, 7, ...
    assert event_occurs_on_date(event, datetime.date(2026, 5, 4)) is True
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is False


def test_event_occurs_on_date_weekly_byday_match():
    event = MagicMock(recurrence_ends_at=None)
    # 2026-05-04 is a Monday.
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)
    event.recurrence = "FREQ=WEEKLY;BYDAY=MO,WE"
    # Wednesday May 6 — match
    assert event_occurs_on_date(event, datetime.date(2026, 5, 6)) is True
    # Tuesday May 5 — no match
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is False


def test_event_occurs_on_date_weekly_no_byday_uses_start_weekday():
    # A FREQ=WEEKLY rule with no BYDAY must recur only on the event's start
    # weekday (RFC 5545 DTSTART semantics), not every day of the week. The SDK
    # omits BYDAY when an event is created without explicit recurrence_days, so
    # this is the common case for "Out of Office" blocks created from a start
    # datetime — matching every day silently zeroed out other days' slots.
    event = MagicMock(recurrence_ends_at=None)
    # 2026-05-04 is a Monday.
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)
    event.recurrence = "FREQ=WEEKLY"
    # Following Monday — matches the start weekday.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11)) is True
    # Tuesday / Wednesday — different weekday, must NOT match.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is False
    assert event_occurs_on_date(event, datetime.date(2026, 5, 6)) is False


def test_event_occurs_on_date_weekly_interval_skip():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)
    event.recurrence = "FREQ=WEEKLY;INTERVAL=2"
    # 1 week later (skipped) — should not match
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11)) is False
    # 2 weeks later — matches
    assert event_occurs_on_date(event, datetime.date(2026, 5, 18)) is True


def test_event_occurs_on_date_unsupported_freq():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=YEARLY"
    assert event_occurs_on_date(event, datetime.date(2027, 5, 1)) is False


def test_event_occurs_on_date_recurrence_ends_at_stops_series():
    # Canvas stores the recurrence end in the recurrence_ends_at column, not as
    # an UNTIL inside the RRULE. A bounded "Out of Office" (ends June 6) must
    # NOT recur past that date — otherwise it zeroes out availability forever.
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 6, 1, 8, 0)
    event.recurrence = "RRULE:FREQ=DAILY"
    event.recurrence_ends_at = datetime.datetime(2026, 6, 6, 4, 59)
    # Within the window — still blocks.
    assert event_occurs_on_date(event, datetime.date(2026, 6, 3)) is True
    # After the recurrence end — must not block.
    assert event_occurs_on_date(event, datetime.date(2026, 6, 15)) is False


def test_event_occurs_on_date_no_recurrence_ends_at_runs_indefinitely():
    # When recurrence_ends_at is unset, a daily rule keeps recurring.
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 6, 1, 8, 0)
    event.recurrence = "RRULE:FREQ=DAILY"
    event.recurrence_ends_at = None
    assert event_occurs_on_date(event, datetime.date(2026, 6, 15)) is True


# _event_window_on_date --------------------------------------------------

def test_event_window_no_dates():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = None
    event.ends_at = None
    assert _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC")) is None


def test_event_window_normal_day():
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 4, 14, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 4, 18, 0, tzinfo=datetime.timezone.utc)
    win = _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC"))
    assert win is not None
    assert win[0] == datetime.datetime(2026, 5, 7, 14, 0, 0)
    assert win[1] == datetime.datetime(2026, 5, 7, 18, 0, 0)


def test_event_window_spans_midnight_caps():
    event = MagicMock(recurrence_ends_at=None)
    # 23:00 local Monday → 02:00 local Tuesday
    event.starts_at = datetime.datetime(2026, 5, 4, 23, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 5, 2, 0, tzinfo=datetime.timezone.utc)
    win = _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC"))
    assert win is not None
    assert win[1] == datetime.datetime(2026, 5, 7, 23, 59, 59)


def test_event_window_end_before_start_returns_none():
    # Same-day event with end <= start.
    event = MagicMock(recurrence_ends_at=None)
    event.starts_at = datetime.datetime(2026, 5, 4, 18, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 4, 18, 0, tzinfo=datetime.timezone.utc)
    win = _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC"))
    assert win is None


# _staff_calendars -------------------------------------------------------

def test_get_availability_windows_keys_events_by_pk_not_id():
    """Regression: Calendar.id is a UUIDField, not the primary key.

    Event.calendar (FK) points to Calendar's auto-int pk, so the FK column
    Event.calendar_id holds that int, not the UUID. Grouping events by
    cal.id would never find them — must use cal.pk.
    """
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.pk = 99
    cal.id = "uuid-not-pk"  # different from pk on purpose
    cal.title = "Bob: Clinic: Loc"
    cal.timezone = "UTC"

    event = MagicMock(recurrence_ends_at=None)
    event.calendar_id = 99  # FK column = pk
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 7, 17, 0, tzinfo=datetime.timezone.utc)
    event.recurrence = None

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = [event]
        result = get_availability_windows("p1", "Loc", "2026-05-07")
        # If the cache key mismatch regresses, this returns [].
        assert len(result) == 1


def test_staff_calendars_dedupes_by_id():
    staff = MagicMock()
    staff.id = "staff-uuid"
    staff.full_name = "Bob Smith"

    cal_a = MagicMock()
    cal_a.id = "cal-1"
    cal_b_dup = MagicMock()
    cal_b_dup.id = "cal-1"  # same ID as cal_a — the in-Python dedup pass should drop it

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal:
        mock_cal.objects.filter.return_value.distinct.return_value = [cal_a, cal_b_dup]
        result = _staff_calendars(staff, "Clinic")
        assert len(result) == 1


# get_location_timezone --------------------------------------------------

def test_get_location_timezone_staff_not_found():
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.objects.get.side_effect = StaffCls.DoesNotExist
        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        assert get_location_timezone("p1", "loc") == "UTC"


def test_get_location_timezone_no_match_returns_utc():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_location_timezone("p1", "loc") == "UTC"


def test_get_location_timezone_returns_calendar_tz():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob Smith"
    primary = MagicMock()
    primary.full_name = "Loc"
    staff.primary_practice_location = primary

    cal = MagicMock()
    cal.title = "Bob Smith: Clinic"  # No location → primary location used.
    cal.timezone = "America/New_York"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_location_timezone("p1", "Loc") == "America/New_York"


def test_get_location_timezone_no_primary_location_skips():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob Smith"
    staff.primary_practice_location = None

    cal = MagicMock()
    cal.title = "Bob Smith: Clinic"
    cal.timezone = "America/New_York"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_location_timezone("p1", "Loc") == "UTC"


def test_get_location_timezone_explicit_location_match():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.title = "Bob: Clinic: Loc"
    cal.timezone = "America/Chicago"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_location_timezone("p1", "Loc") == "America/Chicago"


def test_get_location_timezone_explicit_location_no_match_skips():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.title = "Bob: Clinic: OtherLoc"
    cal.timezone = "America/Chicago"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_location_timezone("p1", "Loc") == "UTC"


# get_availability_windows ----------------------------------------------

def test_get_availability_windows_staff_not_found():
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.objects.get.side_effect = StaffCls.DoesNotExist
        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        assert get_availability_windows("p1", "loc", "2026-05-07") == []


def test_get_availability_windows_no_calendars():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_availability_windows("p1", "loc", "2026-05-07") == []


def test_get_availability_windows_full_path():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.pk = 42  # Calendar's true PK is a Django auto-int, not the .id UUID
    cal.id = "cal-1"
    cal.title = "Bob: Clinic: Loc"
    cal.timezone = "UTC"

    event = MagicMock(recurrence_ends_at=None)
    event.calendar_id = 42  # FK column stores the pk
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 7, 17, 0, tzinfo=datetime.timezone.utc)
    event.recurrence = None

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = [event]
        result = get_availability_windows("p1", "Loc", "2026-05-07")
        assert len(result) == 1


def test_get_availability_windows_invalid_tz_falls_back_to_utc():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.title = "Bob: Clinic: Loc"
    cal.timezone = "Bad/Zone"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = []
        result = get_availability_windows("p1", "Loc", "2026-05-07")
        assert result == []


def test_get_availability_windows_explicit_location_no_match():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.title = "Bob: Clinic: OtherLoc"
    cal.timezone = "UTC"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = []
        assert get_availability_windows("p1", "Loc", "2026-05-07") == []


def test_get_availability_windows_no_primary_location_skips():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"
    staff.primary_practice_location = None

    cal = MagicMock()
    cal.title = "Bob: Clinic"  # generic, requires primary location match
    cal.timezone = "UTC"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = []
        assert get_availability_windows("p1", "Loc", "2026-05-07") == []


# get_blocking_calendar_events ------------------------------------------

def test_get_blocking_calendar_events_invalid_date():
    assert get_blocking_calendar_events("p1", "bad-date") == []


def test_get_blocking_calendar_events_staff_not_found():
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.objects.get.side_effect = StaffCls.DoesNotExist
        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        assert get_blocking_calendar_events("p1", "2026-05-07") == []


def test_get_blocking_calendar_events_invalid_tz_falls_back():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_blocking_calendar_events("p1", "2026-05-07", "Bad/Zone") == []


def test_get_blocking_calendar_events_returns_blocks():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.pk = 7
    cal.id = "cal-1"
    cal.title = "Bob: admin"

    event = MagicMock(recurrence_ends_at=None)
    event.calendar_id = 7
    event.starts_at = datetime.datetime(2026, 5, 7, 12, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 7, 13, 0, tzinfo=datetime.timezone.utc)
    event.recurrence = None

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = [event]
        result = get_blocking_calendar_events("p1", "2026-05-07", "UTC")
        assert len(result) == 1


# get_providers_for_location ---------------------------------------------

def test_get_providers_for_location_explicit_match():
    cal = MagicMock()
    cal.title = "Bob Smith: Clinic: Loc"

    provider = MagicMock()
    provider.id = "p1"
    provider.full_name = "Bob Smith"
    provider.primary_practice_location = None

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls:
        mock_cal_cls.objects.filter.return_value = [cal]
        mock_staff_cls.objects.filter.return_value.exclude.return_value.distinct.return_value.select_related.return_value = [
            provider
        ]
        result = get_providers_for_location("Loc", ["MD"])
        assert result == [{"id": "p1", "name": "Bob Smith"}]


def test_get_providers_for_location_generic_match_via_primary():
    cal = MagicMock()
    cal.title = "Bob: Clinic"  # no location

    provider = MagicMock()
    provider.id = "p1"
    provider.full_name = "Bob"
    primary = MagicMock()
    primary.full_name = "Loc"
    provider.primary_practice_location = primary

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls:
        mock_cal_cls.objects.filter.return_value = [cal]
        mock_staff_cls.objects.filter.return_value.exclude.return_value.distinct.return_value.select_related.return_value = [
            provider
        ]
        result = get_providers_for_location("Loc", ["MD"])
        assert result == [{"id": "p1", "name": "Bob"}]


def test_get_providers_for_location_skips_non_clinic_calendar():
    cal = MagicMock()
    cal.title = "Bob: admin: Loc"

    provider = MagicMock()
    provider.id = "p1"
    provider.full_name = "Bob"
    provider.primary_practice_location = None

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls:
        mock_cal_cls.objects.filter.return_value = [cal]
        mock_staff_cls.objects.filter.return_value.exclude.return_value.distinct.return_value.select_related.return_value = [
            provider
        ]
        result = get_providers_for_location("Loc", ["MD"])
        assert result == []


def test_get_providers_for_location_dedupes_by_id():
    cal1 = MagicMock()
    cal1.title = "Bob: Clinic: Loc"
    cal2 = MagicMock()
    cal2.title = "Bob: Clinic: Loc"

    provider = MagicMock()
    provider.id = "p1"
    provider.full_name = "Bob"
    provider.primary_practice_location = None

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls:
        mock_cal_cls.objects.filter.return_value = [cal1, cal2]
        # The same staff appears twice (e.g. has two roles).
        mock_staff_cls.objects.filter.return_value.exclude.return_value.distinct.return_value.select_related.return_value = [
            provider
        ]
        result = get_providers_for_location("Loc", ["MD"])
        assert len(result) == 1


def test_day_map_known_keys():
    assert _DAY_MAP["MO"] == 0
    assert _DAY_MAP["SU"] == 6


# _resolve_staff / _resolve_calendars cache helpers ---------------------

def test_resolve_staff_no_cache_queries_each_call():
    staff = MagicMock()
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        mock_staff.objects.get.return_value = staff
        result = _resolve_staff("p1", None)
        assert result is staff


def test_resolve_staff_cache_hit_skips_query():
    cache = {"p1": "cached"}
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        result = _resolve_staff("p1", cache)
        assert result == "cached"
        # Verify no DB call was made.
        assert mock_staff.objects.mock_calls == []


def test_resolve_staff_cache_miss_then_populates():
    cache: dict = {}
    staff = MagicMock()
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        mock_staff.objects.get.return_value = staff
        _resolve_staff("p1", cache)
        # Second call — already cached, no extra DB call
        _resolve_staff("p1", cache)
        # Only one .get call total.
        get_calls = [c for c in mock_staff.objects.mock_calls if c[0] == "get"]
        assert len(get_calls) == 1


def test_resolve_staff_does_not_exist_caches_none():
    cache: dict = {}
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.objects.get.side_effect = StaffCls.DoesNotExist
        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        result = _resolve_staff("p-bad", cache)
        assert result is None
        assert cache == {"p-bad": None}


def test_resolve_calendars_cache_hit():
    staff = MagicMock()
    staff.id = "p1"
    cache = {("p1", "Clinic"): ["cached-cal"]}
    with patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars"
    ) as mock_inner:
        result = _resolve_calendars(staff, "Clinic", cache)
        assert result == ["cached-cal"]
        # Inner function not called on cache hit.
        assert mock_inner.mock_calls == []


def test_resolve_calendars_no_cache_calls_inner():
    staff = MagicMock()
    staff.id = "p1"
    with patch(
        "scheduling_with_rooms.utils.calendar_availability._staff_calendars",
        return_value=["cal-1"],
    ):
        result = _resolve_calendars(staff, "Clinic", None)
        assert result == ["cal-1"]


def test_get_availability_windows_uses_staff_cache():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.id = "cal-1"
    cal.title = "Bob: Clinic: Loc"
    cal.timezone = "UTC"

    staff_cache = {"p1": staff}
    cal_cache = {("p1", "Clinic"): [cal]}

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_event_cls.objects.filter.return_value = []
        get_availability_windows(
            "p1", "Loc", "2026-05-07",
            staff_cache=staff_cache, calendar_cache=cal_cache,
        )
        # Staff and Calendar lookups skipped via cache.
        assert mock_staff_cls.objects.mock_calls == []


def test_get_blocking_calendar_events_uses_staff_cache():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"

    cal = MagicMock()
    cal.id = "cal-1"
    cal.title = "Bob: admin"

    staff_cache = {"p1": staff}
    cal_cache = {("p1", "admin"): [cal]}

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "scheduling_with_rooms.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_event_cls.objects.filter.return_value = []
        get_blocking_calendar_events(
            "p1", "2026-05-07", "UTC",
            staff_cache=staff_cache, calendar_cache=cal_cache,
        )
        assert mock_staff_cls.objects.mock_calls == []


def test_fetch_clinic_calendars():
    from scheduling_with_rooms.utils.calendar_availability import (
        _fetch_clinic_calendars,
    )

    cal = MagicMock()
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal:
        mock_cal.objects.filter.return_value = [cal]
        result = _fetch_clinic_calendars()
        assert result == [cal]


def test_fetch_schedulable_staff():
    from scheduling_with_rooms.utils.calendar_availability import (
        _fetch_schedulable_staff,
    )

    staff = MagicMock()
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        mock_staff.objects.filter.return_value.exclude.return_value.distinct.return_value.select_related.return_value = [
            staff
        ]
        result = _fetch_schedulable_staff(["MD"])
        assert result == [staff]


def test_get_providers_for_location_uses_prefetched_data():
    cal = MagicMock()
    cal.title = "Bob: Clinic: Loc"

    provider = MagicMock()
    provider.id = "p1"
    provider.full_name = "Bob"
    provider.primary_practice_location = None

    # When clinic_calendars and schedulable_staff are provided, no DB calls.
    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Calendar"
    ) as mock_cal, patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff:
        result = get_providers_for_location(
            "Loc",
            ["MD"],
            clinic_calendars=[cal],
            schedulable_staff=[provider],
        )
        assert result == [{"id": "p1", "name": "Bob"}]
        assert mock_cal.objects.mock_calls == []
        assert mock_staff.objects.mock_calls == []


def test_get_location_timezone_uses_staff_cache():
    staff = MagicMock()
    staff.id = "p1"
    staff.full_name = "Bob"
    staff.primary_practice_location = MagicMock(full_name="Loc")

    cal = MagicMock()
    cal.title = "Bob: Clinic"
    cal.timezone = "America/New_York"

    staff_cache = {"p1": staff}
    cal_cache = {("p1", "Clinic"): [cal]}

    with patch(
        "scheduling_with_rooms.utils.calendar_availability.Staff"
    ) as mock_staff_cls:
        result = get_location_timezone(
            "p1", "Loc",
            staff_cache=staff_cache, calendar_cache=cal_cache,
        )
        assert result == "America/New_York"
        assert mock_staff_cls.objects.mock_calls == []
