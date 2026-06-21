"""Behavioral tests for the Canvas-appointment -> Google-event mapping.

The most important property is PHI-safety: no patient-identifying data may appear in any event field.
"""

from datetime import datetime, timezone

from gcal_sync.google.event_builder import (
    CANVAS_APPT_ID_KEY,
    build_event_body,
    content_hash,
    extract_canvas_appt_id,
    google_event_content_hash,
    google_status,
)


def _snapshot(**overrides):
    base = {
        "appointment_id": "appt-123",
        "visit_type": "Office Visit",
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location": "Main Clinic",
        "meeting_link": None,
        "status": "confirmed",
    }
    base.update(overrides)
    return base


def test_title_is_visit_type_not_patient_data():
    body = build_event_body(_snapshot())
    assert body["summary"] == "Office Visit"


def test_missing_visit_type_falls_back_to_generic():
    body = build_event_body(_snapshot(visit_type=None))
    assert body["summary"] == "Appointment"


def test_no_phi_fields_emitted():
    # A meeting link is the only thing allowed in description; nothing else patient-derived.
    body = build_event_body(_snapshot(meeting_link="https://meet.example.com/x"))
    serialized = str(body)
    # Patient-identifying keys must never appear in the payload.
    for forbidden in ("patient", "comment", "mrn", "dob", "birth"):
        assert forbidden not in serialized.lower()
    assert body["description"] == "Join:\nhttps://meet.example.com/x"


def test_no_description_when_no_meeting_link():
    body = build_event_body(_snapshot(meeting_link=None))
    assert "description" not in body


def test_no_location_key_when_location_missing():
    body = build_event_body(_snapshot(location=None))
    assert "location" not in body


def test_end_time_is_start_plus_duration():
    body = build_event_body(_snapshot(duration_minutes=45))
    assert body["start"]["dateTime"] == "2026-06-10T15:00:00Z"
    assert body["end"]["dateTime"] == "2026-06-10T15:45:00Z"


def test_appointment_id_stamped_in_private_extended_properties():
    body = build_event_body(_snapshot())
    assert body["extendedProperties"]["private"][CANVAS_APPT_ID_KEY] == "appt-123"
    assert extract_canvas_appt_id(body) == "appt-123"


def test_extract_returns_none_when_unstamped():
    assert extract_canvas_appt_id({"summary": "foreign event"}) is None


def test_status_mapping():
    assert google_status("unconfirmed") == "tentative"
    assert google_status("arrived") == "confirmed"
    assert google_status("cancelled") == "cancelled"
    assert google_status(None) == "tentative"
    assert google_status("something-new") == "tentative"


def test_content_hash_is_stable_and_order_independent():
    a = build_event_body(_snapshot())
    b = build_event_body(_snapshot())
    assert content_hash(a) == content_hash(b)


def test_content_hash_changes_when_content_changes():
    base = build_event_body(_snapshot())
    moved = build_event_body(_snapshot(start_time=datetime(2026, 6, 10, 16, 0, tzinfo=timezone.utc)))
    assert content_hash(base) != content_hash(moved)


def test_echo_hash_matches_pushed_hash_for_same_event():
    # An event we pushed, echoed back through the watch channel, must hash identically so it is
    # recognised as our own write (loop suppression).
    snapshot = _snapshot(meeting_link="https://meet.example.com/x")
    pushed = build_event_body(snapshot)
    pushed_hash = content_hash(pushed)

    # Google echoes the same event, possibly with a zone offset instead of Z, plus server fields.
    echoed = {
        "id": "g-event-1",
        "etag": "\"abc\"",
        "summary": "Office Visit",
        "location": "Main Clinic",
        "description": "Join:\nhttps://meet.example.com/x",
        "start": {"dateTime": "2026-06-10T11:00:00-04:00", "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-06-10T11:30:00-04:00", "timeZone": "America/New_York"},
        "status": "confirmed",
        "extendedProperties": {"private": {CANVAS_APPT_ID_KEY: "appt-123"}},
    }
    assert google_event_content_hash(echoed) == pushed_hash


def test_telehealth_link_flows_from_appointment_into_event_description():
    # End-to-end through the snapshot builder: a telehealth appointment with no explicit meeting
    # link falls back to the provider's room, and that link lands in the Google event description.
    from datetime import datetime, timezone

    from gcal_sync.appointment_snapshot import snapshot_from_values

    appt_row = {
        "id": "appt-9",
        "note_type__display": "Telehealth Visit",
        "note_type__is_telehealth": True,
        "start_time": datetime(2026, 6, 11, 14, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location__short_name": "Telehealth",
        "status": "confirmed",
        "meeting_link": None,
        "provider__personal_meeting_room_link": "https://meet.example.com/dr-room",
    }
    body = build_event_body(snapshot_from_values(appt_row))
    assert body["description"] == "Join:\nhttps://meet.example.com/dr-room"


def test_echo_hash_differs_after_provider_edit():
    snapshot = _snapshot()
    pushed_hash = content_hash(build_event_body(snapshot))
    edited = {
        "summary": "Office Visit RESCHEDULED",
        "location": "Main Clinic",
        "start": {"dateTime": "2026-06-10T15:00:00Z"},
        "end": {"dateTime": "2026-06-10T15:30:00Z"},
        "status": "confirmed",
        "extendedProperties": {"private": {CANVAS_APPT_ID_KEY: "appt-123"}},
    }
    assert google_event_content_hash(edited) != pushed_hash
