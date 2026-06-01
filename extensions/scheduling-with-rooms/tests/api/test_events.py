"""Tests for api/events.py."""

import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scheduling_with_rooms.api.events import (
    CalendarEventsAPI,
    _calendar_tz,
    _calendar_tz_for_event,
    _parse_dt,
    _serialize_event,
)


# _calendar_tz ----------------------------------------------------------

def test_calendar_tz_empty_id():
    assert _calendar_tz("").key == "UTC"


def test_calendar_tz_no_calendar():
    with patch("scheduling_with_rooms.api.events.Calendar") as mock_cal:
        mock_cal.objects.filter.return_value.first.return_value = None
        assert _calendar_tz("cid").key == "UTC"


def test_calendar_tz_returns_calendar_tz():
    with patch("scheduling_with_rooms.api.events.Calendar") as mock_cal:
        cal = MagicMock()
        cal.timezone = "America/New_York"
        mock_cal.objects.filter.return_value.first.return_value = cal
        assert _calendar_tz("cid").key == "America/New_York"


def test_calendar_tz_invalid_falls_back_to_utc():
    with patch("scheduling_with_rooms.api.events.Calendar") as mock_cal:
        cal = MagicMock()
        cal.timezone = "Bad/Zone"
        mock_cal.objects.filter.return_value.first.return_value = cal
        assert _calendar_tz("cid").key == "UTC"


# _calendar_tz_for_event ------------------------------------------------

def test_calendar_tz_for_event_empty_id():
    assert _calendar_tz_for_event("").key == "UTC"


def test_calendar_tz_for_event_no_event():
    with patch("scheduling_with_rooms.api.events.EventModel") as mock_em:
        mock_em.objects.filter.return_value.select_related.return_value.first.return_value = None
        assert _calendar_tz_for_event("eid").key == "UTC"


def test_calendar_tz_for_event_no_calendar():
    with patch("scheduling_with_rooms.api.events.EventModel") as mock_em:
        ev = MagicMock()
        ev.calendar = None
        mock_em.objects.filter.return_value.select_related.return_value.first.return_value = ev
        assert _calendar_tz_for_event("eid").key == "UTC"


def test_calendar_tz_for_event_returns_tz():
    with patch(
        "scheduling_with_rooms.api.events.EventModel"
    ) as mock_em, patch(
        "scheduling_with_rooms.api.events.Calendar"
    ) as mock_cal:
        ev = MagicMock()
        ev.calendar.id = "cal-1"
        mock_em.objects.filter.return_value.select_related.return_value.first.return_value = ev
        cal = MagicMock()
        cal.timezone = "America/Chicago"
        mock_cal.objects.filter.return_value.first.return_value = cal
        assert _calendar_tz_for_event("eid").key == "America/Chicago"


# _parse_dt -------------------------------------------------------------

def test_parse_dt_none():
    assert _parse_dt(None, ZoneInfo("UTC")) is None
    assert _parse_dt("", ZoneInfo("UTC")) is None


def test_parse_dt_iso_z():
    dt = _parse_dt("2026-05-07T10:00:00Z", ZoneInfo("UTC"))
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_dt_naive_uses_calendar_tz():
    cal_tz = ZoneInfo("America/New_York")
    dt = _parse_dt("2026-05-07T10:00:00", cal_tz)
    assert dt.tzinfo == cal_tz


def test_parse_dt_arrow_fallback():
    # Pass a date that fromisoformat won't accept but arrow will.
    dt = _parse_dt("2026/05/07 10:00:00", ZoneInfo("UTC"))
    assert dt is not None


# _serialize_event ------------------------------------------------------

def _make_event(
    title="Bob: Clinic: Loc",
    description="prov-1",
    starts_at=None,
    ends_at=None,
    recurrence="",
):
    cal = MagicMock()
    cal.id = "cal-1"
    cal.title = title
    cal.description = description
    cal.timezone = "UTC"

    event = MagicMock()
    event.id = "ev-1"
    event.title = "Title"
    event.calendar = cal
    event.starts_at = starts_at
    event.ends_at = ends_at
    event.recurrence = recurrence
    event.recurrence_ends_at = None
    event.allowed_note_types.all.return_value = []
    return event


def test_serialize_event_basic():
    starts = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    ends = datetime.datetime(2026, 5, 7, 11, 0, tzinfo=datetime.timezone.utc)
    event = _make_event(starts_at=starts, ends_at=ends)

    provider = MagicMock()
    provider.id = "prov-1"
    provider.full_name = "Bob"
    provider.primary_practice_location = None

    location = MagicMock()
    location.id = "loc-1"
    location.full_name = "Loc"

    result = _serialize_event(event, [provider], [location])
    assert result["id"] == "ev-1"
    assert result["provider"] == "prov-1"
    assert result["location"] == "loc-1"


def test_serialize_event_match_by_full_name():
    starts = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    ends = datetime.datetime(2026, 5, 7, 11, 0, tzinfo=datetime.timezone.utc)
    # Empty description forces fallback to title-name match.
    event = _make_event(description="", starts_at=starts, ends_at=ends)

    provider = MagicMock()
    provider.id = "prov-1"
    provider.full_name = "Bob"
    provider.primary_practice_location = None

    location = MagicMock()
    location.id = "loc-1"
    location.full_name = "Loc"

    result = _serialize_event(event, [provider], [location])
    assert result["provider"] == "prov-1"


def test_serialize_event_uses_primary_location_for_generic_calendar():
    starts = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    ends = datetime.datetime(2026, 5, 7, 11, 0, tzinfo=datetime.timezone.utc)
    # Title without location → primary location used as fallback.
    event = _make_event(title="Bob: Clinic", starts_at=starts, ends_at=ends)

    primary = MagicMock()
    primary.id = "loc-primary"

    provider = MagicMock()
    provider.id = "prov-1"
    provider.full_name = "Bob"
    provider.primary_practice_location = primary

    result = _serialize_event(event, [provider], [])
    assert result["location"] == "loc-primary"


def test_serialize_event_with_recurrence():
    starts = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    ends = datetime.datetime(2026, 5, 7, 11, 0, tzinfo=datetime.timezone.utc)
    event = _make_event(
        starts_at=starts,
        ends_at=ends,
        recurrence="RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE",
    )

    result = _serialize_event(event, [], [])
    assert result["daysOfWeek"] == ["MO", "WE"]
    assert result["recurrence"]["type"] == "WEEKLY"
    assert result["recurrence"]["interval"] == 2


def test_serialize_event_no_calendar():
    event = MagicMock()
    event.id = "ev-1"
    event.title = "Title"
    event.calendar = None
    event.starts_at = None
    event.ends_at = None
    event.recurrence = ""
    event.recurrence_ends_at = None
    event.allowed_note_types.all.return_value = []

    result = _serialize_event(event, [], [])
    assert result["calendarId"] == ""


def test_serialize_event_invalid_calendar_tz_falls_back_to_utc():
    starts = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    cal = MagicMock()
    cal.id = "cal-1"
    cal.title = "Bob: Clinic"
    cal.description = ""
    cal.timezone = "Bad/Zone"

    event = MagicMock()
    event.id = "ev-1"
    event.title = "Title"
    event.calendar = cal
    event.starts_at = starts
    event.ends_at = starts
    event.recurrence = ""
    event.recurrence_ends_at = None
    event.allowed_note_types.all.return_value = []

    result = _serialize_event(event, [], [])
    assert result["calendarTimezone"] == "Bad/Zone"


def test_serialize_event_with_view_tz():
    starts = datetime.datetime(2026, 5, 7, 10, 0, tzinfo=datetime.timezone.utc)
    event = _make_event(starts_at=starts, ends_at=starts)
    view_tz = ZoneInfo("America/Chicago")
    result = _serialize_event(event, [], [], view_tz=view_tz)
    # Should produce a non-empty startTime
    assert result["startTime"]


# CalendarEventsAPI methods ---------------------------------------------

def _handler(body=None, query_params=None):
    h = CalendarEventsAPI.__new__(CalendarEventsAPI)
    request = MagicMock()
    request.json.return_value = body or {}
    request.query_params = query_params or {}
    h.request = request
    h.secrets = {}
    return h


def test_get_no_tz_param():
    h = _handler(query_params={"tz": ""})
    with patch(
        "scheduling_with_rooms.api.events.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.api.events.PracticeLocation"
    ) as mock_loc, patch(
        "scheduling_with_rooms.api.events.EventModel"
    ) as mock_em, patch(
        "scheduling_with_rooms.api.events._serialize_event",
        return_value={"id": "ev-1"},
    ):
        mock_staff.objects.filter.return_value.select_related.return_value.distinct.return_value = []
        mock_loc.objects.filter.return_value = []
        mock_em.objects.all.return_value.select_related.return_value.prefetch_related.return_value = [MagicMock()]
        result = h.get()
        assert len(result) == 1


def test_get_invalid_tz_falls_back():
    h = _handler(query_params={"tz": "Bad/Zone"})
    with patch(
        "scheduling_with_rooms.api.events.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.api.events.PracticeLocation"
    ) as mock_loc, patch(
        "scheduling_with_rooms.api.events.EventModel"
    ) as mock_em, patch(
        "scheduling_with_rooms.api.events._serialize_event",
        return_value={"id": "ev-1"},
    ):
        mock_staff.objects.filter.return_value.select_related.return_value.distinct.return_value = []
        mock_loc.objects.filter.return_value = []
        mock_em.objects.all.return_value.select_related.return_value.prefetch_related.return_value = []
        result = h.get()
        assert len(result) == 1


def test_get_with_valid_tz():
    h = _handler(query_params={"tz": "America/Chicago"})
    with patch(
        "scheduling_with_rooms.api.events.Staff"
    ) as mock_staff, patch(
        "scheduling_with_rooms.api.events.PracticeLocation"
    ) as mock_loc, patch(
        "scheduling_with_rooms.api.events.EventModel"
    ) as mock_em, patch(
        "scheduling_with_rooms.api.events._serialize_event",
        return_value={"id": "ev-1"},
    ):
        mock_staff.objects.filter.return_value.select_related.return_value.distinct.return_value = []
        mock_loc.objects.filter.return_value = []
        mock_em.objects.all.return_value.select_related.return_value.prefetch_related.return_value = []
        result = h.get()
        assert len(result) == 1


def test_post_with_body_timezone():
    h = _handler({
        "calendar": "cal-1",
        "timezone": "America/New_York",
        "title": "Office Hours",
        "startTime": "2026-05-07T09:00:00",
        "endTime": "2026-05-07T17:00:00",
        "recurrenceFrequency": "WEEKLY",
        "recurrenceInterval": 1,
        "recurrenceDays": ["MO"],
        "recurrenceEndsAt": "2026-12-31T17:00:00",
        "allowedNoteTypes": [],
    })
    with patch("scheduling_with_rooms.api.events.Event") as mock_event:
        mock_event.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2


def test_post_invalid_tz_falls_back_to_calendar():
    h = _handler({
        "calendar": "cal-1",
        "timezone": "Bad/Zone",
        "title": "Office",
        "startTime": "2026-05-07T09:00:00",
        "endTime": "2026-05-07T17:00:00",
    })
    with patch(
        "scheduling_with_rooms.api.events.Event"
    ) as mock_event, patch(
        "scheduling_with_rooms.api.events._calendar_tz",
        return_value=ZoneInfo("UTC"),
    ):
        mock_event.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2


def test_post_no_recurrence():
    h = _handler({
        "calendar": "cal-1",
        "title": "Office",
        "startTime": "2026-05-07T09:00:00",
        "endTime": "2026-05-07T17:00:00",
    })
    with patch(
        "scheduling_with_rooms.api.events.Event"
    ) as mock_event, patch(
        "scheduling_with_rooms.api.events._calendar_tz",
        return_value=ZoneInfo("UTC"),
    ):
        mock_event.return_value.create.return_value = MagicMock(name="effect")
        result = h.post()
        assert len(result) == 2


def test_patch_with_body_tz():
    h = _handler({
        "eventId": "ev-1",
        "timezone": "America/New_York",
        "title": "Updated",
        "startTime": "2026-05-07T09:00:00",
        "endTime": "2026-05-07T17:00:00",
        "recurrenceFrequency": "WEEKLY",
        "recurrenceInterval": 1,
        "recurrenceDays": ["MO"],
        "recurrenceEndsAt": "2026-12-31T17:00:00",
        "allowedNoteTypes": [],
    })
    with patch("scheduling_with_rooms.api.events.Event") as mock_event:
        mock_event.return_value.update.return_value = MagicMock(name="effect")
        result = h.patch()
        assert len(result) == 2


def test_patch_invalid_tz_falls_back():
    h = _handler({
        "eventId": "ev-1",
        "timezone": "Bad/Zone",
        "title": "Updated",
        "startTime": "2026-05-07T09:00:00",
        "endTime": "2026-05-07T17:00:00",
    })
    with patch(
        "scheduling_with_rooms.api.events.Event"
    ) as mock_event, patch(
        "scheduling_with_rooms.api.events._calendar_tz_for_event",
        return_value=ZoneInfo("UTC"),
    ):
        mock_event.return_value.update.return_value = MagicMock(name="effect")
        result = h.patch()
        assert len(result) == 2


def test_patch_no_body_tz():
    h = _handler({
        "eventId": "ev-1",
        "title": "Updated",
        "startTime": "2026-05-07T09:00:00",
        "endTime": "2026-05-07T17:00:00",
    })
    with patch(
        "scheduling_with_rooms.api.events.Event"
    ) as mock_event, patch(
        "scheduling_with_rooms.api.events._calendar_tz_for_event",
        return_value=ZoneInfo("UTC"),
    ):
        mock_event.return_value.update.return_value = MagicMock(name="effect")
        result = h.patch()
        assert len(result) == 2


def test_delete():
    h = _handler({"eventId": "ev-1"})
    with patch("scheduling_with_rooms.api.events.Event") as mock_event:
        mock_event.return_value.delete.return_value = MagicMock(name="effect")
        result = h.delete()
        assert len(result) == 2
