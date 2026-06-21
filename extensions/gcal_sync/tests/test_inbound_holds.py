"""Tests for inbound_holds: event classification, toggles, window parsing, and hold building."""

from gcal_sync.inbound_holds import (
    PRIVATE_EVENT_LABEL,
    build_hold_effect,
    ingest_all_day_events,
    ingest_private_events,
    is_all_day,
    is_private,
    parse_event_window,
    provider_and_location,
    schedule_event_note_type_id,
)


def test_is_private():
    assert is_private({"visibility": "private"})
    assert is_private({"visibility": "confidential"})
    assert not is_private({"visibility": "public"})
    assert not is_private({})


def test_is_all_day():
    assert is_all_day({"start": {"date": "2026-06-22"}})
    assert not is_all_day({"start": {"dateTime": "2026-06-22T09:00:00Z"}})
    assert not is_all_day({})


def test_ingest_toggle_defaults():
    assert ingest_private_events({}) is True
    assert ingest_private_events({"INGEST_PRIVATE_EVENTS": "false"}) is False
    assert ingest_all_day_events({}) is False
    assert ingest_all_day_events({"INGEST_ALL_DAY_EVENTS": "true"}) is True


def test_parse_event_window_timed():
    start, dur = parse_event_window(
        {
            "start": {"dateTime": "2026-06-22T09:00:00+00:00"},
            "end": {"dateTime": "2026-06-22T09:45:00+00:00"},
        }
    )
    assert dur == 45


def test_parse_event_window_defaults_30_without_end():
    _, dur = parse_event_window({"start": {"dateTime": "2026-06-22T09:00:00+00:00"}})
    assert dur == 30


def test_parse_event_window_none_without_start():
    assert parse_event_window({}) is None


def test_schedule_event_note_type_id_prefers_code(mocker):
    nt = mocker.patch("gcal_sync.inbound_holds.NoteType")
    nt.objects.filter.return_value.values_list.return_value.first.return_value = "nt-code"
    assert schedule_event_note_type_id({}) == "nt-code"


def test_schedule_event_note_type_id_none_when_no_type(mocker):
    nt = mocker.patch("gcal_sync.inbound_holds.NoteType")
    chain = nt.objects.filter.return_value.values_list.return_value
    chain.first.return_value = None
    chain.order_by.return_value.first.return_value = None
    assert schedule_event_note_type_id({}) is None


def test_provider_and_location_resolves(mocker):
    scm = mocker.patch("gcal_sync.inbound_holds.StaffCalendarMapping")
    scm.objects.filter.return_value.values_list.return_value.first.return_value = "14"
    staff = mocker.patch("gcal_sync.inbound_holds.Staff")
    staff.objects.filter.return_value.values_list.return_value.first.return_value = "loc-1"
    assert provider_and_location("cal") == ("14", "loc-1")


def test_provider_and_location_none_without_mapping(mocker):
    scm = mocker.patch("gcal_sync.inbound_holds.StaffCalendarMapping")
    scm.objects.filter.return_value.values_list.return_value.first.return_value = None
    assert provider_and_location("cal") is None


def test_provider_and_location_none_without_location(mocker):
    scm = mocker.patch("gcal_sync.inbound_holds.StaffCalendarMapping")
    scm.objects.filter.return_value.values_list.return_value.first.return_value = "14"
    staff = mocker.patch("gcal_sync.inbound_holds.Staff")
    staff.objects.filter.return_value.values_list.return_value.first.return_value = None
    assert provider_and_location("cal") is None


def _timed_event(**extra):
    e = {
        "id": "g1",
        "start": {"dateTime": "2026-06-22T09:00:00+00:00"},
        "end": {"dateTime": "2026-06-22T09:30:00+00:00"},
    }
    e.update(extra)
    return e


def test_build_hold_effect_masks_private_title(mocker):
    # Context (note-type, provider, location) is now passed in pre-resolved by the caller.
    mocker.patch("gcal_sync.inbound_holds.AppointmentIdentifier")
    se = mocker.patch("gcal_sync.inbound_holds.ScheduleEvent")
    build_hold_effect(_timed_event(visibility="private", summary="Dad - Dr. Appt"), "nt-1", "14", "loc-1")
    assert se.call_args.kwargs["description"] == PRIVATE_EVENT_LABEL


def test_build_hold_effect_uses_summary_when_public(mocker):
    mocker.patch("gcal_sync.inbound_holds.AppointmentIdentifier")
    se = mocker.patch("gcal_sync.inbound_holds.ScheduleEvent")
    build_hold_effect(_timed_event(summary="Standup"), "nt-1", "14", "loc-1")
    assert se.call_args.kwargs["description"] == "Standup"
    se.return_value.create.assert_called_once()


def test_build_hold_effect_none_without_note_type():
    assert build_hold_effect(_timed_event(), None, "14", "loc-1") is None


def test_build_hold_effect_none_without_provider():
    assert build_hold_effect(_timed_event(), "nt-1", None, None) is None


def test_build_hold_effect_none_when_time_unparseable():
    assert build_hold_effect({"id": "g1"}, "nt-1", "14", "loc-1") is None
