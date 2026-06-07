from types import SimpleNamespace

from urgent_care_self_scheduler.handlers.api import (
    BookAPI,
    _build_task_title,
    _intake_to_metadata_value,
    _validate_intake_payload,
)


# ---- _validate_intake_payload ----------------------------------------------


def _good_intake() -> dict:
    return {
        "reason_for_visit": "Sore throat for 2 days, mild fever",
        "symptom_duration": "2 days",
        "medications": {"no_changes": True, "changes": []},
        "allergies": {"no_changes": True, "changes": []},
    }


def test_validate_intake_passes_for_full_payload() -> None:
    assert _validate_intake_payload(_good_intake()) is None


def test_validate_intake_rejects_missing_rfv() -> None:
    intake = _good_intake()
    intake["reason_for_visit"] = ""
    err = _validate_intake_payload(intake)
    assert err is not None and "reason_for_visit" in err


def test_validate_intake_rejects_whitespace_only_rfv() -> None:
    intake = _good_intake()
    intake["reason_for_visit"] = "   "
    err = _validate_intake_payload(intake)
    assert err is not None and "reason_for_visit" in err


def test_validate_intake_rejects_rfv_over_500_chars() -> None:
    intake = _good_intake()
    intake["reason_for_visit"] = "x" * 501
    err = _validate_intake_payload(intake)
    assert err is not None and "500" in err


def test_validate_intake_accepts_rfv_at_500_chars() -> None:
    intake = _good_intake()
    intake["reason_for_visit"] = "x" * 500
    assert _validate_intake_payload(intake) is None


def test_validate_intake_rejects_missing_symptom_duration() -> None:
    intake = _good_intake()
    intake["symptom_duration"] = ""
    err = _validate_intake_payload(intake)
    assert err is not None and "symptom_duration" in err


def test_validate_intake_rejects_non_dict_payload() -> None:
    err = _validate_intake_payload("not a dict")  # type: ignore[arg-type]
    assert err is not None


# ---- _build_task_title ------------------------------------------------------


def test_task_title_includes_patient_name_and_visit_summary() -> None:
    title = _build_task_title("Jane Doe", "Sore throat for 2 days, mild fever")
    assert "Jane Doe" in title
    assert "Sore throat" in title


def test_task_title_truncates_long_rfv() -> None:
    title = _build_task_title("Jane Doe", "x" * 400)
    assert len(title) < 200


# ---- _intake_to_metadata_value ---------------------------------------------


def test_intake_to_metadata_value_serializes_intake_to_json_string() -> None:
    intake = _good_intake()
    value = _intake_to_metadata_value(intake)
    assert isinstance(value, str)
    # Must roundtrip via json.
    import json
    assert json.loads(value) == intake


# ---- BookAPI ----------------------------------------------------------------


def test_book_api_path() -> None:
    assert BookAPI.PATH == "/api/book"


def test_book_api_authenticate_accepts_patient() -> None:
    api = BookAPI.__new__(BookAPI)
    creds = SimpleNamespace(logged_in_user={"id": "p-1", "type": "Patient"})
    assert api.authenticate(creds) is True


def test_book_api_authenticate_rejects_staff() -> None:
    import pytest
    from canvas_sdk.handlers.simple_api.security import InvalidCredentialsError

    api = BookAPI.__new__(BookAPI)
    creds = SimpleNamespace(logged_in_user={"id": "s-1", "type": "Staff"})
    with pytest.raises(InvalidCredentialsError):
        api.authenticate(creds)


# ---- BookAPI.post branches --------------------------------------------------


def _make_book_api(
    *,
    secrets: dict | None = None,
    headers: dict | None = None,
    body: bytes = b"{}",
) -> BookAPI:
    api = BookAPI.__new__(BookAPI)
    api.secrets = secrets if secrets is not None else {  # type: ignore[attr-defined]
        "URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care",
    }
    api.request = SimpleNamespace(  # type: ignore[attr-defined]
        headers=headers if headers is not None else {"canvas-logged-in-user-id": "p-1"},
        body=body,
    )
    return api


def test_book_api_returns_503_when_secret_missing() -> None:
    api = _make_book_api(secrets={})
    response = api.post()
    assert response[0].status_code == 503


def test_book_api_returns_401_when_no_session_header() -> None:
    api = _make_book_api(headers={})
    response = api.post()
    assert response[0].status_code == 401


def test_book_api_returns_400_for_invalid_json() -> None:
    api = _make_book_api(body=b"{not-json")
    response = api.post()
    assert response[0].status_code == 400


def test_book_api_returns_400_for_invalid_intake() -> None:
    import json as _json
    body = _json.dumps({
        "slot": {"provider_id": "x", "start_iso": "y"},
        "intake": {"reason_for_visit": "", "symptom_duration": "1 day"},
    }).encode()
    api = _make_book_api(body=body)
    response = api.post()
    assert response[0].status_code == 400


def test_book_api_returns_400_for_missing_slot_fields() -> None:
    import json as _json
    body = _json.dumps({
        "slot": {"provider_id": ""},
        "intake": _good_intake(),
    }).encode()
    api = _make_book_api(body=body)
    response = api.post()
    assert response[0].status_code == 400


def test_book_api_returns_409_when_slot_no_longer_available(mocker) -> None:
    import json as _json
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.resolve_urgent_care_note_type",
        return_value=SimpleNamespace(id="nt-1", online_duration=15),
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[],  # nothing available
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._active_location",
        return_value=(None, __import__("zoneinfo").ZoneInfo("UTC")),
    )
    body = _json.dumps({
        "slot": {"provider_id": "p-x", "start_iso": "2026-05-01T08:00:00+00:00"},
        "intake": _good_intake(),
    }).encode()
    api = _make_book_api(body=body)
    response = api.post()
    assert response[0].status_code == 409


def test_book_api_blocks_when_patient_already_has_urgent_care_visit(mocker) -> None:
    import json as _json
    from canvas_sdk.v1.data.note import NoteType

    fake_slot = {
        "provider_id": "p-1",
        "provider_name": "Dr. Smith",
        "start_iso": "2026-05-01T08:00:00+00:00",
        "end_iso": "2026-05-01T08:15:00+00:00",
    }
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[fake_slot],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._active_location",
        return_value=("loc-1", __import__("zoneinfo").ZoneInfo("UTC")),
    )
    # Patient already has an upcoming urgent-care visit (any day in the window).
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_has_upcoming_urgent_care_visit",
        return_value=True,
    )
    note_type = SimpleNamespace(
        id="nt-1",
        online_duration=15,
        is_active=True,
        is_scheduleable=True,
        is_scheduleable_via_patient_portal=True,
    )
    mocker.patch.object(NoteType.objects, "filter", return_value=[note_type])

    body = _json.dumps({
        "slot": {"provider_id": "p-1", "start_iso": fake_slot["start_iso"]},
        "intake": _good_intake(),
    }).encode()
    response = _make_book_api(body=body).post()
    assert response[0].status_code == 409
    assert _json.loads(response[0].content)["error"] == "already_has_urgent_care"


def test_book_api_happy_path_returns_effects_and_response(mocker) -> None:
    """Happy path uses canvas[test-utils] factories so AppointmentEffect's
    validate-against-DB checks pass.
    """
    import json as _json
    from canvas_sdk.test_utils.factories import (
        NoteTypeFactory,
        PatientFactory,
        PracticeLocationFactory,
        StaffFactory,
    )
    from canvas_sdk.v1.data.note import NoteType

    patient = PatientFactory.create()
    provider = StaffFactory.create()
    location = PracticeLocationFactory.create()

    note_type = NoteTypeFactory.create(
        name="Urgent Care",
        is_active=True,
        is_scheduleable=True,
        is_scheduleable_via_patient_portal=True,
        category="encounter",
        is_telehealth=True,
    )
    # Factory default for online_duration may be None — required by AppointmentEffect.
    note_type.online_duration = 15
    note_type.save()

    fake_slot = {
        "provider_id": str(provider.id),
        "provider_name": "Dr. Smith",
        "start_iso": "2026-05-01T08:00:00+00:00",
        "end_iso": "2026-05-01T08:15:00+00:00",
    }
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[fake_slot],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._active_location",
        return_value=(str(location.id), __import__("zoneinfo").ZoneInfo("UTC")),
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_full_name",
        return_value="Jane Doe",
    )
    mocker.patch.object(NoteType.objects, "filter", return_value=[note_type])

    body = _json.dumps({
        "slot": {"provider_id": str(provider.id), "start_iso": fake_slot["start_iso"]},
        "intake": _good_intake(),
    }).encode()
    api = BookAPI.__new__(BookAPI)
    api.secrets = {"URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care"}  # type: ignore[attr-defined]
    api.request = SimpleNamespace(  # type: ignore[attr-defined]
        headers={"canvas-logged-in-user-id": str(patient.id)},
        body=body,
    )
    response = api.post()
    # rfv stash + appointment + task + task-comment(symptom duration) + JSON response
    assert len(response) == 5
    payload = _json.loads(response[-1].content)
    assert payload["ok"] is True
    assert payload["start_iso"] == fake_slot["start_iso"]
    assert payload["provider_name"] == "Dr. Smith"
    # Even with no flagged changes, the task comment carries the symptom duration.
    from canvas_sdk.effects import EffectType
    comment_effects = [
        e for e in response if getattr(e, "type", None) == EffectType.CREATE_TASK_COMMENT
    ]
    assert len(comment_effects) == 1
    assert "Symptom duration: 2 days" in comment_effects[0].payload


def test_book_api_surfaces_flagged_med_allergy_changes_on_task(mocker) -> None:
    """When the patient flags med/allergy changes, they must be surfaced on the
    intake task (title flag + a task comment), not only in the note's HPI.
    """
    import json as _json
    from canvas_sdk.effects import EffectType
    from canvas_sdk.test_utils.factories import (
        NoteTypeFactory,
        PatientFactory,
        PracticeLocationFactory,
        StaffFactory,
    )
    from canvas_sdk.v1.data.note import NoteType

    patient = PatientFactory.create()
    provider = StaffFactory.create()
    location = PracticeLocationFactory.create()
    note_type = NoteTypeFactory.create(
        name="Urgent Care",
        is_active=True,
        is_scheduleable=True,
        is_scheduleable_via_patient_portal=True,
        category="encounter",
        is_telehealth=True,
    )
    note_type.online_duration = 15
    note_type.save()

    fake_slot = {
        "provider_id": str(provider.id),
        "provider_name": "Dr. Smith",
        "start_iso": "2026-05-01T08:00:00+00:00",
        "end_iso": "2026-05-01T08:15:00+00:00",
    }
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[fake_slot],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._active_location",
        return_value=(str(location.id), __import__("zoneinfo").ZoneInfo("UTC")),
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_full_name",
        return_value="Jane Doe",
    )
    mocker.patch.object(NoteType.objects, "filter", return_value=[note_type])

    intake = {
        "reason_for_visit": "Sore throat",
        "symptom_duration": "2 days",
        "medications": {
            "no_changes": False,
            "changes": [{"medication_id": "m1", "label": "Lisinopril 10mg", "note": "stopped taking it"}],
        },
        "allergies": {
            "no_changes": False,
            "changes": [{"allergy_id": "a1", "label": "Penicillin", "note": "new rash"}],
        },
    }
    body = _json.dumps({
        "slot": {"provider_id": str(provider.id), "start_iso": fake_slot["start_iso"]},
        "intake": intake,
    }).encode()
    api = BookAPI.__new__(BookAPI)
    api.secrets = {"URGENT_CARE_NOTE_TYPE_NAME": "Urgent Care"}  # type: ignore[attr-defined]
    api.request = SimpleNamespace(  # type: ignore[attr-defined]
        headers={"canvas-logged-in-user-id": str(patient.id)},
        body=body,
    )
    response = api.post()

    # appointment + task + task-comment + rfv stash + JSON response
    assert len(response) == 5
    comment_effects = [
        e for e in response if getattr(e, "type", None) == EffectType.CREATE_TASK_COMMENT
    ]
    assert len(comment_effects) == 1
    assert "Symptom duration: 2 days" in comment_effects[0].payload
    assert "Lisinopril 10mg" in comment_effects[0].payload
    assert "stopped taking it" in comment_effects[0].payload
    assert "Penicillin" in comment_effects[0].payload
    task_effects = [
        e for e in response if getattr(e, "type", None) == EffectType.CREATE_TASK
    ]
    assert "med/allergy changes flagged" in task_effects[0].payload


def test_book_api_returns_503_when_note_type_resolution_returns_zero(mocker) -> None:
    import json as _json
    from canvas_sdk.v1.data.note import NoteType

    fake_slot = {
        "provider_id": "00000000-0000-0000-0000-000000000001",
        "provider_name": "Dr. Smith",
        "start_iso": "2026-05-01T08:00:00+00:00",
        "end_iso": "2026-05-01T08:15:00+00:00",
    }
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[fake_slot],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._practice_timezone",
        return_value=__import__("zoneinfo").ZoneInfo("UTC"),
    )
    # Zero candidates → handler returns 503.
    mocker.patch.object(NoteType.objects, "filter", return_value=[])

    body = _json.dumps({
        "slot": {"provider_id": "00000000-0000-0000-0000-000000000001", "start_iso": fake_slot["start_iso"]},
        "intake": _good_intake(),
    }).encode()
    api = _make_book_api(body=body)
    response = api.post()
    assert response[0].status_code == 503


def test_book_api_returns_503_when_no_practice_location(mocker) -> None:
    import json as _json
    from canvas_sdk.v1.data.note import NoteType

    fake_slot = {
        "provider_id": "00000000-0000-0000-0000-000000000001",
        "provider_name": "Dr. Smith",
        "start_iso": "2026-05-01T08:00:00+00:00",
        "end_iso": "2026-05-01T08:15:00+00:00",
    }
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api.find_available_slots",
        return_value=[fake_slot],
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._active_location",
        return_value=(None, __import__("zoneinfo").ZoneInfo("UTC")),
    )
    mocker.patch(
        "urgent_care_self_scheduler.handlers.api._patient_has_upcoming_urgent_care_visit",
        return_value=False,
    )
    fake_note_type = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000002",
        online_duration=15,
        is_active=True,
        is_scheduleable=True,
        is_scheduleable_via_patient_portal=True,
    )
    mocker.patch.object(NoteType.objects, "filter", return_value=[fake_note_type])

    body = _json.dumps({
        "slot": {"provider_id": "00000000-0000-0000-0000-000000000001", "start_iso": fake_slot["start_iso"]},
        "intake": _good_intake(),
    }).encode()
    api = _make_book_api(body=body)
    response = api.post()
    assert response[0].status_code == 503
