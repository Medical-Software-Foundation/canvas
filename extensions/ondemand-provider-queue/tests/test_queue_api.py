"""Routes: authentication, the off switch, input checks and the visit lifecycle."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from canvas_sdk.handlers.simple_api import SessionCredentials
from canvas_sdk.handlers.simple_api.exceptions import InvalidCredentialsError
from canvas_sdk.test_utils.factories import PatientFactory, StaffFactory

from canvas__ondemand_provider_queue.handlers import queue_api
from canvas__ondemand_provider_queue.handlers.queue_api import QueueAPI, QueueIntakeAPI
from canvas__ondemand_provider_queue.storage.canvas_store import CanvasQueueStore

KEY = "k" * 40
ON = {
    "QUEUE_ENABLED": "true",
    "QUEUE_API_KEY": KEY,
    "DEFAULT_NOTE_TYPE_ID": "note-type-1",
    "DEFAULT_PRACTICE_LOCATION_ID": "loc-1",
}


def make(
    cls: Any,
    body: Any = None,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    secrets: dict[str, str] | None = None,
) -> Any:
    event = MagicMock()
    event.context = {"method": "POST", "path": "/"}
    handler = cls(event, secrets if secrets is not None else ON)
    handler.request = MagicMock(headers=headers or {}, query_params=query or {})
    if isinstance(body, Exception):
        handler.request.json.side_effect = body
    else:
        handler.request.json.return_value = body
    return handler


def staff_headers(staff_id: str = "staff-1") -> dict[str, str]:
    return {"canvas-logged-in-user-type": "Staff", "canvas-logged-in-user-id": staff_id}


def payload(result: list[Any]) -> tuple[int, dict[str, Any]]:
    response = result[0]
    return response.status_code, json.loads(response.content)


@pytest.fixture
def note_effect(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    note = MagicMock()
    note.return_value.create.return_value = "NOTE_EFFECT"
    monkeypatch.setattr(queue_api, "Note", note)
    return note


# --- authentication ---


def test_intake_requires_matching_bearer_key() -> None:
    auth = MagicMock()
    assert make(QueueIntakeAPI, headers={"authorization": f"Bearer {KEY}"}).authenticate(auth)
    assert not make(QueueIntakeAPI, headers={"authorization": "Bearer wrong"}).authenticate(auth)
    assert not make(QueueIntakeAPI, headers={"authorization": KEY}).authenticate(auth)
    assert not make(QueueIntakeAPI).authenticate(auth)


def test_intake_refuses_everything_without_a_configured_key() -> None:
    handler = make(QueueIntakeAPI, headers={"authorization": "Bearer "}, secrets={})
    assert not handler.authenticate(MagicMock())


def session(user_type: str, user_id: str) -> Any:
    return MagicMock(logged_in_user={"type": user_type, "id": user_id})


def test_staff_routes_need_a_staff_session() -> None:
    assert make(QueueAPI).authenticate(session("Staff", "staff-1"))
    with pytest.raises(InvalidCredentialsError):
        make(QueueAPI).authenticate(session("Patient", "p"))
    # Without session headers the SDK refuses before authenticate runs.
    with pytest.raises(InvalidCredentialsError):
        SessionCredentials(make(QueueAPI, headers={"authorization": f"Bearer {KEY}"}).request)


def test_staff_allow_list() -> None:
    secrets = {**ON, "QUEUE_STAFF_IDS": "staff-1, staff-2"}
    assert make(QueueAPI, secrets=secrets).authenticate(session("Staff", "staff-2"))
    assert not make(QueueAPI, secrets=secrets).authenticate(session("Staff", "staff-9"))


# --- off switch ---


def test_everything_is_off_by_default() -> None:
    off = {"QUEUE_API_KEY": KEY}
    status, body = payload(make(QueueIntakeAPI, {"patient_id": "x"}, secrets=off).queue_request())
    assert status == 503 and body["success"] is False
    assert payload(make(QueueAPI, secrets=off).queue())[0] == 503
    assert payload(make(QueueAPI, {"entry_id": "x"}, secrets=off).start_visit())[0] == 503


def test_half_configured_s3_answers_503() -> None:
    secrets = {**ON, "QUEUE_STORAGE": "s3"}
    assert payload(make(QueueAPI, secrets=secrets).queue())[0] == 503


# --- intake ---


def test_intake_validates_input() -> None:
    patient = PatientFactory.create()
    assert payload(make(QueueIntakeAPI, {}).queue_request())[0] == 400
    assert payload(make(QueueIntakeAPI, ["not", "a", "dict"]).queue_request())[0] == 400
    bad_json = make(QueueIntakeAPI, json.JSONDecodeError("bad", "", 0))
    assert payload(bad_json.queue_request())[0] == 400
    wrong_priority = {"patient_id": patient.id, "reason_for_visit": "x", "priority": "<b>"}
    assert payload(make(QueueIntakeAPI, wrong_priority).queue_request())[0] == 400
    unknown = {"patient_id": "nobody", "reason_for_visit": "x"}
    assert payload(make(QueueIntakeAPI, unknown).queue_request())[0] == 404


def test_intake_creates_once_per_external_id() -> None:
    patient = PatientFactory.create()
    body = {"patient_id": patient.id, "reason_for_visit": "Follow-up", "external_id": "req-1"}
    result = make(QueueIntakeAPI, body).queue_request()
    status, first = payload(result)
    assert status == 201 and first["created"] is True and len(result) == 2  # + broadcast
    again = make(QueueIntakeAPI, body).queue_request()
    status, second = payload(again)
    assert status == 200 and second["entry_id"] == first["entry_id"] and len(again) == 1


# --- staff screen ---


def test_page_config_and_staff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_api, "render_to_string", lambda path: "<html></html>")
    assert make(QueueAPI, headers=staff_headers()).queue_page()[0].status_code == 200

    status, config = payload(make(QueueAPI).config())
    assert status == 200 and config == {"enabled": True, "demo_mode_enabled": False}

    StaffFactory.create(first_name="Zed", last_name="Last", active=True)
    StaffFactory.create(first_name="Amy", last_name="First", active=True)
    StaffFactory.create(first_name="Gone", last_name="Inactive", active=False)
    status, data = payload(make(QueueAPI, headers=staff_headers("me")).staff())
    names = [s["name"] for s in data["staff"]]
    assert names.index("Amy First") < names.index("Zed Last") and "Gone Inactive" not in names
    assert data["current_user"] == {"id": "me"}


def test_queue_lists_open_and_completed_with_patient_details() -> None:
    patient = PatientFactory.create(first_name="Test", last_name="Patient")
    store = CanvasQueueStore()
    open_entry, _ = store.create_entry(patient.id, "Follow-up")
    done, _ = store.create_entry(patient.id, "Done")
    store.claim_entry(done.id, "s", "n")
    store.start_entry(done.id, "note-1")
    store.complete_for_note("note-1", None)

    status, data = payload(make(QueueAPI).queue())
    assert status == 200 and [e["id"] for e in data["entries"]] == [open_entry.id]
    row = data["entries"][0]
    assert row["patient_name"] == "Test Patient" and "patient_age" in row

    _, completed = payload(make(QueueAPI, query={"view": "completed"}).queue())
    assert [e["id"] for e in completed["entries"]] == [done.id]


def test_claim_and_assign() -> None:
    me = StaffFactory.create(first_name="Me", last_name="Doc", active=True)
    other = StaffFactory.create(first_name="Other", last_name="Doc", active=True)
    store = CanvasQueueStore()
    entry, _ = store.create_entry("pat-1", "Follow-up")

    assert payload(make(QueueAPI, {}, headers=staff_headers(me.id)).claim_entry())[0] == 400
    status, data = payload(
        make(QueueAPI, {"entry_id": entry.id}, staff_headers(me.id)).claim_entry()
    )
    assert status == 200 and data["entry"]["assigned_provider_name"] == "Me Doc"

    # A second person can't take it.
    assign = {"entry_id": entry.id, "action": "assign", "staff_id": other.id}
    status, data = payload(make(QueueAPI, assign).update_assignment())
    assert status == 409 and data["error"] == "Entry already claimed"

    unassign = {"entry_id": entry.id, "action": "unassign"}
    assert payload(make(QueueAPI, unassign).update_assignment())[0] == 200
    status, data = payload(make(QueueAPI, assign).update_assignment())
    assert status == 200 and data["entry"]["assigned_provider_id"] == other.id


def test_assignment_input_checks() -> None:
    entry, _ = CanvasQueueStore().create_entry("pat-1", "Follow-up")
    assert payload(make(QueueAPI, {"entry_id": entry.id}).update_assignment())[0] == 400
    no_staff = {"entry_id": entry.id, "action": "assign"}
    assert payload(make(QueueAPI, no_staff).update_assignment())[0] == 400
    unknown_staff = {**no_staff, "staff_id": "nobody"}
    assert payload(make(QueueAPI, unknown_staff).update_assignment())[0] == 404
    missing = {"entry_id": "missing", "action": "unassign"}
    assert payload(make(QueueAPI, missing).update_assignment())[0] == 404


def test_start_visit_creates_one_note(note_effect: MagicMock) -> None:
    store = CanvasQueueStore()
    entry, _ = store.create_entry("pat-1", "Follow-up")
    store.claim_entry(entry.id, "staff-1", "Dr A")

    result = make(QueueAPI, {"entry_id": entry.id}).start_visit()
    status, data = payload(result)
    assert status == 200 and "NOTE_EFFECT" in result
    kwargs = note_effect.call_args.kwargs
    assert kwargs["instance_id"] == data["note_id"]
    assert (kwargs["patient_id"], kwargs["provider_id"]) == ("pat-1", "staff-1")
    assert kwargs["practice_location_id"] == "loc-1"

    again = make(QueueAPI, {"entry_id": entry.id}).start_visit()
    assert payload(again)[1]["note_id"] == data["note_id"]
    assert len(again) == 1 and note_effect.call_count == 1  # no second note


def test_start_visit_refusals(note_effect: MagicMock) -> None:
    store = CanvasQueueStore()
    assert payload(make(QueueAPI, {}).start_visit())[0] == 404
    entry, _ = store.create_entry("pat-1", "Follow-up")
    # Not assigned yet.
    assert payload(make(QueueAPI, {"entry_id": entry.id}).start_visit())[0] == 400
    store.claim_entry(entry.id, "staff-1", "Dr A")
    # Missing note type setting.
    no_type = {k: v for k, v in ON.items() if k != "DEFAULT_NOTE_TYPE_ID"}
    assert payload(make(QueueAPI, {"entry_id": entry.id}, secrets=no_type).start_visit())[0] == 400
    # Paused visit can't be started again.
    store.start_entry(entry.id, "note-1")
    store.pause_entry(entry.id)
    assert payload(make(QueueAPI, {"entry_id": entry.id}).start_visit())[0] == 409
    assert note_effect.call_count == 0


def test_pause_and_resume_routes() -> None:
    store = CanvasQueueStore()
    entry, _ = store.create_entry("pat-1", "Follow-up")
    assert payload(make(QueueAPI, {"entry_id": entry.id}).pause_visit())[0] == 409
    store.claim_entry(entry.id, "staff-1", "Dr A")
    store.start_entry(entry.id, "note-1")
    status, data = payload(make(QueueAPI, {"entry_id": entry.id}).pause_visit())
    assert status == 200 and data["entry"]["status"] == "paused"
    status, data = payload(make(QueueAPI, {"entry_id": entry.id}).resume_visit())
    assert status == 200 and data["entry"]["status"] == "in_progress"


# --- demo tools ---


def test_demo_tools_are_off_by_default() -> None:
    assert payload(make(QueueAPI).demo_add_patient())[0] == 403
    assert payload(make(QueueAPI).demo_clear_queue())[0] == 403


def test_demo_adds_only_listed_test_patients() -> None:
    demo = {**ON, "DEMO_MODE_ENABLED": "true", "DEMO_PATIENT_IDS": "test-a,test-b"}
    added = {
        payload(make(QueueAPI, secrets=demo).demo_add_patient())[1]["entry_id"] for _ in range(2)
    }
    patients = {e.patient_id for e in CanvasQueueStore().list_entries(("awaiting_assignment",))}
    assert len(added) == 2 and patients == {"test-a", "test-b"}
    assert payload(make(QueueAPI, secrets=demo).demo_add_patient())[0] == 409  # none left

    status, data = payload(make(QueueAPI, secrets=demo).demo_clear_queue())
    assert status == 200 and data["removed"] == 2
