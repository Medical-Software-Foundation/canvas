"""Tests for appointment_snapshot: meeting-link resolution, snapshot building, origin lookup."""

from datetime import datetime, timezone

from gcal_sync.appointment_snapshot import (
    build_snapshot,
    google_origin_event_id,
    resolve_meeting_link,
    snapshot_from_values,
)


def test_resolve_meeting_link_prefers_explicit():
    assert resolve_meeting_link({"meeting_link": "https://room/x"}) == "https://room/x"


def test_resolve_meeting_link_telehealth_personal_room():
    appt = {"note_type__is_telehealth": True, "provider__personal_meeting_room_link": "https://r/y"}
    assert resolve_meeting_link(appt) == "https://r/y"


def test_resolve_meeting_link_none_for_in_person():
    assert resolve_meeting_link({"note_type__is_telehealth": False}) is None


def _appt(**extra):
    base = {
        "id": 1,
        "provider__id": 14,
        "note_type__display": "Office Visit",
        "note_type__category": "appointment",
        "note_type__is_telehealth": False,
        "start_time": datetime(2026, 6, 20, 19, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location__short_name": "Clinic NY",
        "status": "confirmed",
        "meeting_link": None,
        "description": "",
        "provider__personal_meeting_room_link": None,
    }
    base.update(extra)
    return base


def test_snapshot_from_values_appointment_uses_visit_type():
    snap = snapshot_from_values(_appt())
    assert snap["visit_type"] == "Office Visit"
    assert snap["meeting_link"] is None
    assert snap["appointment_id"] == "1"


def test_snapshot_from_values_schedule_event_uses_description_no_link():
    snap = snapshot_from_values(
        _appt(note_type__category="schedule_event", description="Lunch", note_type__is_telehealth=True)
    )
    assert snap["visit_type"] == "Lunch"
    assert snap["meeting_link"] is None  # schedule events never carry a link


def test_build_snapshot_returns_tuple(mocker):
    appt = mocker.patch("gcal_sync.appointment_snapshot.Appointment")
    appt.objects.filter.return_value.values.return_value.first.return_value = _appt()
    result = build_snapshot("1")
    assert result is not None
    snap, provider_id, is_sched = result
    assert provider_id == "14"
    assert is_sched is False


def test_build_snapshot_none_when_missing(mocker):
    appt = mocker.patch("gcal_sync.appointment_snapshot.Appointment")
    appt.objects.filter.return_value.values.return_value.first.return_value = None
    assert build_snapshot("1") is None


def test_build_snapshot_none_without_provider(mocker):
    appt = mocker.patch("gcal_sync.appointment_snapshot.Appointment")
    appt.objects.filter.return_value.values.return_value.first.return_value = _appt(provider__id=None)
    assert build_snapshot("1") is None


def test_google_origin_event_id_found(mocker):
    ext = mocker.patch("gcal_sync.appointment_snapshot.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value.first.return_value = "g-123"
    assert google_origin_event_id("1") == "g-123"


def test_google_origin_event_id_none(mocker):
    ext = mocker.patch("gcal_sync.appointment_snapshot.AppointmentExternalIdentifier")
    ext.objects.filter.return_value.values_list.return_value.first.return_value = None
    assert google_origin_event_id("1") is None
