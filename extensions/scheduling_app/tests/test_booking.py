import json
from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from scheduling_app.booking import build_booking_effects

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.v1.data.note import NoteTypeCategories


@pytest.fixture
def mock_db_queries() -> Generator[None]:
    """Mock the DB existence/lookup queries the appointment effects validate against."""
    with (
        patch("canvas_sdk.v1.data.PracticeLocation.objects") as mock_pl,
        patch("canvas_sdk.v1.data.Staff.objects") as mock_staff,
        patch("canvas_sdk.v1.data.Patient.objects") as mock_patient,
        patch("canvas_sdk.v1.data.NoteType.objects") as mock_note_type,
        patch("canvas_sdk.v1.data.appointment.Appointment.objects") as mock_appointment,
        patch("canvas_sdk.v1.data.appointment.AppointmentLabel.objects") as mock_appt_label,
    ):
        mock_pl.filter.return_value.exists.return_value = True
        mock_staff.filter.return_value.exists.return_value = True
        mock_patient.filter.return_value.exists.return_value = True
        mock_appointment.filter.return_value.exists.return_value = True
        # The reschedule effect validates the label count against existing labels.
        mock_appt_label.filter.return_value.count.return_value = 0
        # Appointment effect: (category, is_scheduleable)
        mock_note_type.values_list.return_value.filter.return_value.get.return_value = (
            NoteTypeCategories.ENCOUNTER,
            True,
        )
        # ScheduleEvent effect: category/patient/title lookup
        mock_note_type.values.return_value.filter.return_value.first.return_value = {
            "category": NoteTypeCategories.SCHEDULE_EVENT,
            "is_patient_required": False,
            "allow_custom_title": True,
        }
        yield


def _appointment_payload(**overrides: object) -> dict:
    payload = {
        "mode": "schedule",
        "category": "appointment",
        "patient_id": "pat-1",
        "grouping": "concurrent",
        "visits": [
            {
                "providers": ["staff-1"],
                "location_id": str(uuid4()),
                "visit_type_id": str(uuid4()),
                "duration_minutes": 30,
                "start_time": "2026-06-10T09:00:00",
                "labels": [],
                "description": "",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _data(effect: object) -> dict:
    return json.loads(effect.payload)["data"]


def test_schedule_single_appointment(mock_db_queries: None) -> None:
    """A single-provider appointment yields one CREATE_APPOINTMENT effect."""
    effects = build_booking_effects(_appointment_payload())

    assert len(effects) == 1
    assert effects[0].type == EffectType.CREATE_APPOINTMENT
    data = _data(effects[0])
    assert data["provider_id"] == "staff-1"
    assert data["patient_id"] == "pat-1"
    assert data["duration_minutes"] == 30
    assert data["start_time"] == "2026-06-10T09:00:00"


def test_multi_provider_concurrent(mock_db_queries: None) -> None:
    """Two providers on one concurrent visit yield two effects at the same start."""
    payload = _appointment_payload()
    payload["visits"][0]["providers"] = ["staff-1", "staff-2"]

    effects = build_booking_effects(payload)

    assert len(effects) == 2
    assert {_data(e)["provider_id"] for e in effects} == {"staff-1", "staff-2"}
    assert {_data(e)["start_time"] for e in effects} == {"2026-06-10T09:00:00"}


def test_sequential_chaining(mock_db_queries: None) -> None:
    """Sequential visits chain: each starts when the previous ends."""
    payload = _appointment_payload(grouping="sequential")
    payload["visits"].append(
        {
            "providers": ["staff-2"],
            "location_id": str(uuid4()),
            "visit_type_id": str(uuid4()),
            "duration_minutes": 15,
            "start_time": "2026-06-10T15:00:00",  # ignored for the 2nd sequential visit
            "labels": [],
            "description": "",
        }
    )

    effects = build_booking_effects(payload)

    assert len(effects) == 2
    assert _data(effects[0])["start_time"] == "2026-06-10T09:00:00"
    assert _data(effects[1])["start_time"] == "2026-06-10T09:30:00"


def test_reschedule_single_appointment(mock_db_queries: None) -> None:
    """Reschedule yields a single RESCHEDULE_APPOINTMENT effect for the appointment."""
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-uuid-9")

    effects = build_booking_effects(payload)

    assert len(effects) == 1
    assert effects[0].type == EffectType.RESCHEDULE_APPOINTMENT
    data = _data(effects[0])
    assert data["instance_id"] == "appt-uuid-9"
    assert data["duration_minutes"] == 30


def test_schedule_event(mock_db_queries: None) -> None:
    """An Other Event yields a CREATE_SCHEDULE_EVENT effect carrying its title."""
    payload = _appointment_payload(category="schedule_event")
    payload["visits"][0]["description"] = "Team huddle"

    effects = build_booking_effects(payload)

    assert len(effects) == 1
    assert effects[0].type == EffectType.CREATE_SCHEDULE_EVENT
    assert _data(effects[0])["description"] == "Team huddle"


def test_free_text_rfv_adds_command_targeting_the_note(mock_db_queries: None) -> None:
    """A free-text RFV adds an RFV command targeting the appointment's note."""
    payload = _appointment_payload()
    payload["visits"][0]["reason_for_visit"] = "Persistent cough"

    effects = build_booking_effects(payload)

    assert len(effects) == 2
    appointment, rfv = effects
    assert appointment.type == EffectType.CREATE_APPOINTMENT
    assert rfv.type == EffectType.ORIGINATE_REASON_FOR_VISIT_COMMAND
    # The command targets the very note the appointment creates (same id).
    assert json.loads(rfv.payload)["note"] == _data(appointment)["instance_id"]
    assert _data(rfv)["comment"] == "Persistent cough"


def test_no_rfv_means_no_command(mock_db_queries: None) -> None:
    """Without a reason for visit, only the appointment effect is emitted."""
    effects = build_booking_effects(_appointment_payload())
    assert [e.type for e in effects] == [EffectType.CREATE_APPOINTMENT]


def test_coded_rfv_adds_structured_command(mock_db_queries: None) -> None:
    """A coded RFV adds a structured command carrying the coding id (+ comment)."""
    coding_id = str(uuid4())
    payload = _appointment_payload()
    payload["visits"][0]["reason_for_visit_coding"] = coding_id
    payload["visits"][0]["reason_for_visit_comment"] = "since Monday"

    # `.originate()` validates the coding exists against the DB; mock it present.
    with patch(
        "canvas_sdk.commands.commands.reason_for_visit.ReasonForVisitSettingCoding.objects"
    ) as mock_coding:
        mock_coding.filter.return_value.exists.return_value = True
        effects = build_booking_effects(payload)

    assert len(effects) == 2
    rfv = effects[1]
    assert rfv.type == EffectType.ORIGINATE_REASON_FOR_VISIT_COMMAND
    data = _data(rfv)
    assert data["coding"] == coding_id
    assert data["comment"] == "since Monday"


def test_schedule_event_ignores_rfv(mock_db_queries: None) -> None:
    """RFV fields on a schedule event are ignored (reason-for-visit is appointment-only)."""
    payload = _appointment_payload(category="schedule_event")
    payload["visits"][0]["reason_for_visit"] = "should be dropped"

    effects = build_booking_effects(payload)

    assert [e.type for e in effects] == [EffectType.CREATE_SCHEDULE_EVENT]


def test_reschedule_edits_existing_rfv(mock_db_queries: None) -> None:
    """Reschedule with an existing RFV edits that command in place by its uuid.

    ``rfv_command_id`` / ``note_id`` are server-injected by the /book handler.
    """
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9", rfv_command_id="cmd-1")
    payload["visits"][0]["reason_for_visit"] = "Updated reason"

    effects = build_booking_effects(payload)

    assert [e.type for e in effects] == [
        EffectType.RESCHEDULE_APPOINTMENT,
        EffectType.EDIT_REASON_FOR_VISIT_COMMAND,
    ]
    edit = json.loads(effects[1].payload)
    assert edit["command"] == "cmd-1"
    assert edit["data"]["comment"] == "Updated reason"


def test_reschedule_originates_rfv_when_none_exists(mock_db_queries: None) -> None:
    """Reschedule with a new reason (no prior command) originates one on the note."""
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9", note_id="note-1")
    payload["visits"][0]["reason_for_visit"] = "New reason"

    effects = build_booking_effects(payload)

    assert [e.type for e in effects] == [
        EffectType.RESCHEDULE_APPOINTMENT,
        EffectType.ORIGINATE_REASON_FOR_VISIT_COMMAND,
    ]
    originate = json.loads(effects[1].payload)
    assert originate["note"] == "note-1"
    assert originate["data"]["comment"] == "New reason"


def test_reschedule_clears_rfv(mock_db_queries: None) -> None:
    """Reschedule that removes the reason retires the existing RFV command."""
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9", rfv_command_id="cmd-1")
    # No reason on the visit → the existing command is entered-in-error.

    effects = build_booking_effects(payload)

    assert [e.type for e in effects] == [
        EffectType.RESCHEDULE_APPOINTMENT,
        EffectType.ENTER_IN_ERROR_REASON_FOR_VISIT_COMMAND,
    ]
    assert json.loads(effects[1].payload)["command"] == "cmd-1"


def test_reschedule_without_rfv_context_is_just_reschedule(mock_db_queries: None) -> None:
    """A reason with no resolved note/command (nothing to target) yields no RFV effect."""
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9")
    payload["visits"][0]["reason_for_visit"] = "ignored — no target id"

    effects = build_booking_effects(payload)

    assert [e.type for e in effects] == [EffectType.RESCHEDULE_APPOINTMENT]


def test_reschedule_sends_labels(mock_db_queries: None) -> None:
    """Reschedule carries the (edited) labels so home-app applies them to the new appt."""
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9")
    payload["visits"][0]["labels"] = ["Emergent", "Urgent"]

    effects = build_booking_effects(payload)

    assert effects[0].type == EffectType.RESCHEDULE_APPOINTMENT
    assert sorted(_data(effects[0])["labels"]) == ["Emergent", "Urgent"]


def test_reschedule_with_labels_bypasses_additive_limit(mock_db_queries: None) -> None:
    """Editing labels on reschedule must not trip the SDK's additive >3 check.

    The SDK validates reschedule labels as existing(old) + new <= 3, so with 2
    existing labels, sending 2 would wrongly error (4 > 3). The plugin builds the
    effect WITHOUT labels (skipping that check) and injects them into the payload
    for home-app's replacement onto the fresh appointment.
    """
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9")
    payload["visits"][0]["labels"] = ["Emergent", "Urgent"]

    # Simulate the old appointment already carrying 2 labels (the bug scenario):
    # under the old code this raised; the injection approach must not.
    with patch("canvas_sdk.v1.data.appointment.AppointmentLabel.objects") as mock_label:
        mock_label.filter.return_value.count.return_value = 2
        effects = build_booking_effects(payload)

    assert effects[0].type == EffectType.RESCHEDULE_APPOINTMENT
    assert sorted(_data(effects[0])["labels"]) == ["Emergent", "Urgent"]


def test_reschedule_always_sends_labels_so_empty_clears(mock_db_queries: None) -> None:
    """Reschedule always sends the field's labels as the authoritative set.

    An empty field sends ``labels: []`` (the key is always present) so home-app
    clears them, rather than copying the original appointment's labels forward.
    """
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9")
    payload["visits"][0]["labels"] = []

    effects = build_booking_effects(payload)

    data = _data(effects[0])
    assert effects[0].type == EffectType.RESCHEDULE_APPOINTMENT
    assert "labels" in data
    assert data["labels"] == []


def test_reschedule_edits_coded_rfv(mock_db_queries: None) -> None:
    """A coded reason on reschedule edits the command as structured (coding id)."""
    coding_id = str(uuid4())
    payload = _appointment_payload(mode="reschedule", appointment_id="appt-9", rfv_command_id="cmd-1")
    payload["visits"][0]["reason_for_visit_coding"] = coding_id
    payload["visits"][0]["reason_for_visit_comment"] = "worsening"

    # `.edit()` validates the coding exists against the DB; mock it present.
    with patch(
        "canvas_sdk.commands.commands.reason_for_visit.ReasonForVisitSettingCoding.objects"
    ) as mock_coding:
        mock_coding.filter.return_value.exists.return_value = True
        effects = build_booking_effects(payload)

    assert effects[1].type == EffectType.EDIT_REASON_FOR_VISIT_COMMAND
    data = json.loads(effects[1].payload)["data"]
    assert data["coding"] == coding_id
    assert data["comment"] == "worsening"
