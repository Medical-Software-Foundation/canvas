"""Structural tests for the push handler and the shared snapshot builder.

The handler is tightly coupled to the SDK event/runtime, so (mirroring the feed tests) we assert the
wiring that this feature depends on: which events it responds to, how it routes them, and that the
appointment fields it reads carry no PHI.
"""

import inspect

from canvas_sdk.events import EventType

from gcal_sync import appointment_snapshot
from gcal_sync.appointment_snapshot import APPOINTMENT_FIELDS
from gcal_sync.handlers import appointment_sync
from gcal_sync.handlers.appointment_sync import AppointmentSyncHandler


def test_responds_to_all_appointment_lifecycle_events():
    expected = {
        EventType.Name(EventType.APPOINTMENT_CREATED),
        EventType.Name(EventType.APPOINTMENT_UPDATED),
        EventType.Name(EventType.APPOINTMENT_RESTORED),
        EventType.Name(EventType.APPOINTMENT_CHECKED_IN),
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    }
    assert set(AppointmentSyncHandler.RESPONDS_TO) == expected


def test_cancel_and_noshow_route_to_delete():
    assert EventType.APPOINTMENT_CANCELED in appointment_sync._DELETE_EVENTS
    assert EventType.APPOINTMENT_NO_SHOWED in appointment_sync._DELETE_EVENTS
    assert EventType.APPOINTMENT_CREATED in appointment_sync._UPSERT_EVENTS


def test_compute_branches_on_delete_vs_upsert():
    src = inspect.getsource(AppointmentSyncHandler.compute)
    assert "_DELETE_EVENTS" in src
    assert "_handle_delete" in src
    assert "_UPSERT_EVENTS" in src
    assert "_handle_upsert" in src


def test_only_expected_google_errors_are_swallowed():
    # Unexpected exceptions must propagate (no bare except Exception).
    src = inspect.getsource(AppointmentSyncHandler._safe)
    assert "except (GoogleApiError, GoogleAuthError, RequestException)" in src
    assert "except Exception" not in src


def test_snapshot_query_filters_entered_in_error():
    src = inspect.getsource(appointment_snapshot.build_snapshot)
    assert "entered_in_error__isnull=True" in src


def test_appointment_fields_carry_no_patient_phi():
    # The patient and patient free-text comment must never be selected.
    joined = " ".join(APPOINTMENT_FIELDS)
    for forbidden in ("patient", "comment", "birth"):
        assert forbidden not in joined
    assert "note_type__display" in APPOINTMENT_FIELDS
    assert "start_time" in APPOINTMENT_FIELDS
    assert "provider__id" in APPOINTMENT_FIELDS


def _row(**overrides):
    from datetime import datetime, timezone

    base = {
        "id": "a1",
        "provider__id": "p1",
        "note_type__display": "Office Visit",
        "note_type__category": "appointment",
        "note_type__is_telehealth": False,
        "start_time": datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc),
        "duration_minutes": 30,
        "location__short_name": "Clinic",
        "status": "confirmed",
        "meeting_link": None,
        "description": "SENSITIVE free text",
        "provider__personal_meeting_room_link": None,
    }
    base.update(overrides)
    return base


def test_appointment_title_is_visit_type_never_description():
    # For a patient appointment the title is the visit type — the description (possible PHI) is ignored.
    from gcal_sync.appointment_snapshot import snapshot_from_values

    snap = snapshot_from_values(_row())
    assert snap["visit_type"] == "Office Visit"
    assert "SENSITIVE" not in str(snap)


def test_schedule_event_title_is_description_and_no_meeting_link():
    # For an admin hold (no patient) the description IS the title, and there's no meeting link.
    from gcal_sync.appointment_snapshot import snapshot_from_values

    snap = snapshot_from_values(
        _row(note_type__category="schedule_event", description="Admin Hold", meeting_link="x")
    )
    assert snap["visit_type"] == "Admin Hold"
    assert snap["meeting_link"] is None
