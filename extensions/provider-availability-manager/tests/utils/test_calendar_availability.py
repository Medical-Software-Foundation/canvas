"""Tests for calendar_availability.py."""

import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from provider_availability_manager.utils.calendar_availability import (
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
    event = MagicMock()
    event.starts_at = None
    assert event_occurs_on_date(event, datetime.date(2026, 5, 7)) is False


def test_event_occurs_on_date_no_recurrence_match():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0)
    event.recurrence = None
    assert event_occurs_on_date(event, datetime.date(2026, 5, 7)) is True


def test_event_occurs_on_date_no_recurrence_no_match():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0)
    event.recurrence = None
    assert event_occurs_on_date(event, datetime.date(2026, 5, 8)) is False


def test_event_occurs_on_date_target_before_start():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0)
    event.recurrence = "FREQ=DAILY"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 1)) is False


def test_event_occurs_on_date_until_passed():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY;UNTIL=20260505T235959"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 10)) is False


def test_event_occurs_on_date_until_invalid_continues():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY;UNTIL=BAD"
    # Should still match daily.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 10)) is True


def test_event_occurs_on_date_daily_interval_one():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is True


def test_event_occurs_on_date_daily_interval_three_match():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=DAILY;INTERVAL=3"
    # Days 1, 4, 7, ...
    assert event_occurs_on_date(event, datetime.date(2026, 5, 4)) is True
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is False


def test_event_occurs_on_date_weekly_byday_match():
    event = MagicMock()
    # 2026-05-04 is a Monday.
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)
    event.recurrence = "FREQ=WEEKLY;BYDAY=MO,WE"
    # Wednesday May 6 — match
    assert event_occurs_on_date(event, datetime.date(2026, 5, 6)) is True
    # Tuesday May 5 — no match
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is False


def test_event_occurs_on_date_weekly_no_byday_matches_only_start_weekday():
    """RFC 5545 + JS UI: FREQ=WEEKLY without BYDAY matches only the weekday
    of DTSTART, not every day in matching weeks.

    Regression: the previous implementation skipped the BYDAY check entirely
    when BYDAY was empty and returned True for every weekday, surfacing
    slots on days the provider never opened (fail-OPEN on an Available
    calendar). The old test was named ``..._always_matches`` and only
    asserted Mon → True on a Mon DTSTART, so it passed whether the
    semantic was "every day" or "match start weekday".
    """
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)  # Monday
    event.recurrence = "FREQ=WEEKLY"
    # Following Monday — same weekday as DTSTART — must match.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11)) is True
    # The next *Tuesday* (2026-05-05) is a different weekday — must NOT
    # match. Pre-fix this returned True.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5)) is False
    # Wed–Sun also must not match.
    for day in range(6, 11):
        assert event_occurs_on_date(event, datetime.date(2026, 5, day)) is False


def test_event_occurs_on_date_weekly_interval_skip():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)
    event.recurrence = "FREQ=WEEKLY;INTERVAL=2"
    # 1 week later (skipped) — should not match
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11)) is False
    # 2 weeks later — matches
    assert event_occurs_on_date(event, datetime.date(2026, 5, 18)) is True


def test_event_occurs_on_date_unsupported_freq():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 1, 9, 0)
    event.recurrence = "FREQ=YEARLY"
    assert event_occurs_on_date(event, datetime.date(2027, 5, 1)) is False


# Timezone regression: evening events in west-of-UTC zones are stored on the
# next UTC day. Without converting to the calendar's local tz before .date(),
# the matcher misses the user's intended local day and the slot filter
# silently drops every evening slot.

def test_event_occurs_on_date_pst_evening_matches_local_monday():
    """A 21:00 Monday PDT event is stored as 04:00 Tuesday UTC. The matcher
    must return True for the local Monday (the user's intent) and False for
    the UTC Tuesday."""
    pdt = ZoneInfo("America/Los_Angeles")
    event = MagicMock()
    # 04:00 UTC on Tuesday May 5 == 21:00 PDT on Monday May 4.
    event.starts_at = datetime.datetime(
        2026, 5, 5, 4, 0, tzinfo=datetime.timezone.utc
    )
    event.recurrence = None

    assert event_occurs_on_date(event, datetime.date(2026, 5, 4), pdt) is True
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5), pdt) is False


def test_event_occurs_on_date_pst_evening_recurring_first_occurrence_not_missed():
    """The recurring-event start guard must compare local dates too. A
    weekly-recurring 'Monday 21:00 PDT' event whose UTC starts_at lands on
    Tuesday must still match its first local Monday."""
    pdt = ZoneInfo("America/Los_Angeles")
    event = MagicMock()
    event.starts_at = datetime.datetime(
        2026, 5, 5, 4, 0, tzinfo=datetime.timezone.utc
    )
    event.recurrence = "FREQ=WEEKLY;BYDAY=MO"

    assert event_occurs_on_date(event, datetime.date(2026, 5, 4), pdt) is True
    # Next Monday should also match.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11), pdt) is True


def test_event_occurs_on_date_tokyo_morning_matches_local_tuesday():
    """The mirror case: a 07:00 Tuesday Tokyo event is stored as 22:00 Monday
    UTC. The matcher must return True for the local Tuesday."""
    tokyo = ZoneInfo("Asia/Tokyo")
    event = MagicMock()
    # 22:00 UTC on Monday May 4 == 07:00 JST on Tuesday May 5.
    event.starts_at = datetime.datetime(
        2026, 5, 4, 22, 0, tzinfo=datetime.timezone.utc
    )
    event.recurrence = None

    assert event_occurs_on_date(event, datetime.date(2026, 5, 5), tokyo) is True
    assert event_occurs_on_date(event, datetime.date(2026, 5, 4), tokyo) is False


def test_event_occurs_on_date_weekly_interval_matches_js_sunday_anchor():
    """WEEKLY+INTERVAL math anchors to Sunday-start calendar weeks (matching
    ``weekStartOf`` in the JS UI), not to rolling 7-day chunks from DTSTART.

    Regression: with DTSTART Tue 2026-05-05 and
    FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH, every Monday's match was inverted
    relative to the UI. The UI rendered Mon 2026-05-11 as a *skipped*
    week and Mon 2026-05-18 as an *active* week; the Python filter saw
    the opposite, so either fail-closed dropped every Monday slot for
    the active week or fail-open exposed slots the user never opened on
    the skipped week.
    """
    event = MagicMock()
    # DTSTART on Tue 2026-05-05 at 09:00 (naive keeps the test focused on
    # the WKST anchor question rather than tz conversion).
    event.starts_at = datetime.datetime(2026, 5, 5, 9, 0)
    event.recurrence = "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH"

    # Per the RFC 5545 / JS interpretation, Mon 2026-05-11 is the *skipped*
    # week (next Sunday-anchored calendar week after DTSTART), and Mon
    # 2026-05-18 is the active week.
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11)) is False
    assert event_occurs_on_date(event, datetime.date(2026, 5, 18)) is True
    # The Thursday in DTSTART's own week still matches (the original
    # DTSTART week is "week 0", always active).
    assert event_occurs_on_date(event, datetime.date(2026, 5, 7)) is True


def test_event_occurs_on_date_weekly_interval_dtstart_monday_aligned():
    """Sanity: the existing 'Monday DTSTART, INTERVAL=2' case is preserved
    because the Sunday anchor matches the rolling-chunk answer when
    DTSTART itself lands on Sun/Mon (the alignment the older test
    depended on)."""
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 4, 9, 0)  # Monday
    event.recurrence = "FREQ=WEEKLY;INTERVAL=2"
    assert event_occurs_on_date(event, datetime.date(2026, 5, 11)) is False
    assert event_occurs_on_date(event, datetime.date(2026, 5, 18)) is True


def test_event_occurs_on_date_daily_interval_uses_local_dates():
    """DAILY interval arithmetic must compute the day delta from the local
    date, not the UTC date. With interval=3 starting 'Monday May 4 PDT'
    (stored as Tuesday May 5 UTC), the next occurrences are Thu May 7 and
    Sun May 10 PDT — not Wed May 6 / Sat May 9."""
    pdt = ZoneInfo("America/Los_Angeles")
    event = MagicMock()
    event.starts_at = datetime.datetime(
        2026, 5, 5, 4, 0, tzinfo=datetime.timezone.utc
    )
    event.recurrence = "FREQ=DAILY;INTERVAL=3"

    assert event_occurs_on_date(event, datetime.date(2026, 5, 4), pdt) is True
    assert event_occurs_on_date(event, datetime.date(2026, 5, 5), pdt) is False
    assert event_occurs_on_date(event, datetime.date(2026, 5, 7), pdt) is True
    assert event_occurs_on_date(event, datetime.date(2026, 5, 10), pdt) is True


# _event_window_on_date --------------------------------------------------

def test_event_window_no_dates():
    event = MagicMock()
    event.starts_at = None
    event.ends_at = None
    assert _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC")) is None


def test_event_window_normal_day():
    event = MagicMock()
    event.starts_at = datetime.datetime(2026, 5, 4, 14, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 4, 18, 0, tzinfo=datetime.timezone.utc)
    win = _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC"))
    assert win is not None
    assert win[0] == datetime.datetime(2026, 5, 7, 14, 0, 0)
    assert win[1] == datetime.datetime(2026, 5, 7, 18, 0, 0)


def test_event_window_spans_midnight_caps():
    event = MagicMock()
    # 23:00 local Monday → 02:00 local Tuesday
    event.starts_at = datetime.datetime(2026, 5, 4, 23, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 5, 2, 0, tzinfo=datetime.timezone.utc)
    win = _event_window_on_date(event, datetime.date(2026, 5, 7), ZoneInfo("UTC"))
    assert win is not None
    assert win[1] == datetime.datetime(2026, 5, 7, 23, 59, 59)


def test_event_window_end_before_start_returns_none():
    # Same-day event with end <= start.
    event = MagicMock()
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

    event = MagicMock()
    event.calendar_id = 99  # FK column = pk
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 7, 17, 0, tzinfo=datetime.timezone.utc)
    event.recurrence = None

    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "provider_availability_manager.utils.calendar_availability.Event"
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
    cal_a.title = "Bob Smith: Clinic"
    cal_b_dup = MagicMock()
    cal_b_dup.id = "cal-1"  # same ID as cal_a — the in-Python dedup pass should drop it
    cal_b_dup.title = "Bob Smith: Clinic"

    with patch(
        "provider_availability_manager.utils.calendar_availability.Calendar"
    ) as mock_cal:
        mock_cal.objects.filter.return_value.distinct.return_value = [cal_a, cal_b_dup]
        result = _staff_calendars(staff, "Clinic")
        assert len(result) == 1


def test_staff_calendars_does_not_match_admin_substring_in_location_name():
    """Regression: a Clinic calendar at a location named "Admin Office" must
    not match a search for type_keyword="admin".

    A documented title is ``"{Name}: {Type}: {Location}"`` — the old DB-side
    ``title__icontains=": admin"`` matched ``": admin"`` *inside* the
    location slot, pulling the Clinic calendar into the admin-block lookup
    and silently zeroing out availability for that provider at every
    location. The fix parses the title and checks the type field exactly.
    """
    staff = MagicMock()
    staff.id = "staff-uuid"
    staff.full_name = "Dr Smith"

    clinic_at_admin_office = MagicMock()
    clinic_at_admin_office.id = "cal-clinic"
    clinic_at_admin_office.title = "Dr Smith: Clinic: Admin Office"

    real_admin_cal = MagicMock()
    real_admin_cal.id = "cal-admin"
    real_admin_cal.title = "Dr Smith: admin"

    with patch(
        "provider_availability_manager.utils.calendar_availability.Calendar"
    ) as mock_cal:
        mock_cal.objects.filter.return_value.distinct.return_value = [
            clinic_at_admin_office, real_admin_cal,
        ]
        result = _staff_calendars(staff, "admin")

    result_ids = [c.id for c in result]
    assert result_ids == ["cal-admin"], (
        "Clinic calendar at 'Admin Office' must not be returned for admin lookup"
    )


def test_staff_calendars_finds_clinic_calendar_at_admin_office_when_searching_clinic():
    """The inverse: a Clinic calendar at "Admin Office" still matches a
    Clinic lookup (so the fix doesn't accidentally exclude it)."""
    staff = MagicMock()
    staff.id = "staff-uuid"
    staff.full_name = "Dr Smith"

    clinic_at_admin_office = MagicMock()
    clinic_at_admin_office.id = "cal-clinic"
    clinic_at_admin_office.title = "Dr Smith: Clinic: Admin Office"

    real_admin_cal = MagicMock()
    real_admin_cal.id = "cal-admin"
    real_admin_cal.title = "Dr Smith: admin"

    with patch(
        "provider_availability_manager.utils.calendar_availability.Calendar"
    ) as mock_cal:
        mock_cal.objects.filter.return_value.distinct.return_value = [
            clinic_at_admin_office, real_admin_cal,
        ]
        result = _staff_calendars(staff, "Clinic")

    assert [c.id for c in result] == ["cal-clinic"]


def test_staff_calendars_matches_type_case_insensitively():
    """``type_keyword`` matching is case-insensitive on both sides.

    Titles in the wild use both ``"Clinic"`` and lower-case ``"admin"``
    (see ``Event.calendar`` SDK constants), and operators sometimes paste
    mixed-case keywords. Parsing + lower-casing keeps the comparison
    stable.
    """
    staff = MagicMock()
    staff.id = "staff-uuid"
    staff.full_name = "Dr Smith"

    cal_lower = MagicMock()
    cal_lower.id = "cal-1"
    cal_lower.title = "Dr Smith: clinic"  # lower-case type in title

    cal_upper = MagicMock()
    cal_upper.id = "cal-2"
    cal_upper.title = "Dr Smith: CLINIC: Loc"

    with patch(
        "provider_availability_manager.utils.calendar_availability.Calendar"
    ) as mock_cal:
        mock_cal.objects.filter.return_value.distinct.return_value = [
            cal_lower, cal_upper,
        ]
        result = _staff_calendars(staff, "Clinic")

    assert {c.id for c in result} == {"cal-1", "cal-2"}


# get_location_timezone --------------------------------------------------

def test_get_location_timezone_staff_not_found():
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ):
        mock_staff_cls.objects.get.return_value = staff
        assert get_location_timezone("p1", "Loc") == "UTC"


# get_availability_windows ----------------------------------------------

def test_get_availability_windows_staff_not_found():
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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

    event = MagicMock()
    event.calendar_id = 42  # FK column stores the pk
    event.starts_at = datetime.datetime(2026, 5, 7, 9, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 7, 17, 0, tzinfo=datetime.timezone.utc)
    event.recurrence = None

    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "provider_availability_manager.utils.calendar_availability.Event"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "provider_availability_manager.utils.calendar_availability.Event"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "provider_availability_manager.utils.calendar_availability.Event"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "provider_availability_manager.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = []
        assert get_availability_windows("p1", "Loc", "2026-05-07") == []


# get_blocking_calendar_events ------------------------------------------

def test_get_blocking_calendar_events_invalid_date():
    assert get_blocking_calendar_events("p1", "bad-date") == []


def test_get_blocking_calendar_events_staff_not_found():
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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

    event = MagicMock()
    event.calendar_id = 7
    event.starts_at = datetime.datetime(2026, 5, 7, 12, 0, tzinfo=datetime.timezone.utc)
    event.ends_at = datetime.datetime(2026, 5, 7, 13, 0, tzinfo=datetime.timezone.utc)
    event.recurrence = None

    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
        return_value=[cal],
    ), patch(
        "provider_availability_manager.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_staff_cls.objects.get.return_value = staff
        mock_event_cls.objects.filter.return_value = [event]
        result = get_blocking_calendar_events("p1", "2026-05-07", "UTC")
        assert len(result) == 1


def test_day_map_known_keys():
    assert _DAY_MAP["MO"] == 0
    assert _DAY_MAP["SU"] == 6


# _resolve_staff / _resolve_calendars cache helpers ---------------------

def test_resolve_staff_no_cache_queries_each_call():
    staff = MagicMock()
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff:
        mock_staff.objects.get.return_value = staff
        result = _resolve_staff("p1", None)
        assert result is staff


def test_resolve_staff_cache_hit_skips_query():
    cache = {"p1": "cached"}
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff:
        result = _resolve_staff("p1", cache)
        assert result == "cached"
        # Verify no DB call was made.
        assert mock_staff.objects.mock_calls == []


def test_resolve_staff_cache_miss_then_populates():
    cache: dict = {}
    staff = MagicMock()
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.objects.get.side_effect = StaffCls.DoesNotExist
        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        result = _resolve_staff("p-bad", cache)
        assert result is None
        assert cache == {"p-bad": None}


def test_resolve_staff_validation_error_falls_through():
    """Regression: ``Staff.id`` is a UUIDField; Django raises
    ``ValidationError`` for non-UUID input. provider_id ultimately comes
    from the undocumented APPOINTMENT__SLOTS__POST_SEARCH payload — if a
    non-UUID value sneaks in, letting the exception propagate would crash
    compute(), suppress the filter effect, and silently flip fail-closed
    into fail-OPEN."""
    from django.core.exceptions import ValidationError

    cache: dict = {}
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        mock_staff.objects.get.side_effect = ValidationError(
            "main-clinic-slug is not a valid UUID."
        )
        result = _resolve_staff("main-clinic-slug", cache)
        assert result is None
        # Cached as None so subsequent lookups don't re-trigger the crash.
        assert cache == {"main-clinic-slug": None}


def test_resolve_staff_value_error_falls_through():
    """Older Django versions raised ``ValueError`` from UUIDField.to_python
    instead of ValidationError. The except clause catches both."""
    cache: dict = {}
    with patch(
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff:
        from canvas_sdk.v1.data.staff import Staff as StaffCls

        mock_staff.DoesNotExist = StaffCls.DoesNotExist
        mock_staff.objects.get.side_effect = ValueError("bad uuid")
        result = _resolve_staff("not-a-uuid", cache)
        assert result is None


def test_resolve_calendars_cache_hit():
    staff = MagicMock()
    staff.id = "p1"
    cache = {("p1", "Clinic"): ["cached-cal"]}
    with patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars"
    ) as mock_inner:
        result = _resolve_calendars(staff, "Clinic", cache)
        assert result == ["cached-cal"]
        # Inner function not called on cache hit.
        assert mock_inner.mock_calls == []


def test_resolve_calendars_no_cache_calls_inner():
    staff = MagicMock()
    staff.id = "p1"
    with patch(
        "provider_availability_manager.utils.calendar_availability._staff_calendars",
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability.Event"
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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls, patch(
        "provider_availability_manager.utils.calendar_availability.Event"
    ) as mock_event_cls:
        mock_event_cls.objects.filter.return_value = []
        get_blocking_calendar_events(
            "p1", "2026-05-07", "UTC",
            staff_cache=staff_cache, calendar_cache=cal_cache,
        )
        assert mock_staff_cls.objects.mock_calls == []


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
        "provider_availability_manager.utils.calendar_availability.Staff"
    ) as mock_staff_cls:
        result = get_location_timezone(
            "p1", "Loc",
            staff_cache=staff_cache, calendar_cache=cal_cache,
        )
        assert result == "America/New_York"
        assert mock_staff_cls.objects.mock_calls == []
