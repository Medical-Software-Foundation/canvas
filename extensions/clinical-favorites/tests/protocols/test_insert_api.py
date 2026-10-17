"""Tests for InsertFavoritesAPI."""

import datetime as dt
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from clinical_favorites.protocols.insert_api import (
    InsertFavoritesAPI,
    _condition_code_resolves,
    _iso,
    _medication_code_resolves,
    _parse_body,
)


PATIENT_ID = "pat-1"
NOTE_UUID = "note-uuid-1"


@pytest.fixture(autouse=True)
def _codes_resolve_by_default():
    """Make ontology validation pass unless a test overrides it.

    Keeps the endpoint tests off the network and focused on routing. The
    validation helpers themselves are covered by their own unit tests below.
    """
    with (
        patch(
            "clinical_favorites.protocols.insert_api._medication_code_resolves",
            return_value=True,
        ),
        patch(
            "clinical_favorites.protocols.insert_api._condition_code_resolves",
            return_value=True,
        ),
    ):
        yield


def _fake_effect(data: dict | None = None) -> MagicMock:
    """Mock an originate Effect whose payload is real JSON for downstream assertions."""
    effect = MagicMock()
    effect.payload = json.dumps({
        "command": "cmd-uuid",
        "note": NOTE_UUID,
        "data": data or {},
        "line_number": -1,
    })
    return effect


def _api(body: dict, staff_id: str | None = "staff-uuid-1") -> InsertFavoritesAPI:
    api = InsertFavoritesAPI(MagicMock())
    api.request = MagicMock()
    api.request.headers = {"canvas-logged-in-user-id": staff_id} if staff_id else {}
    api.request.body = json.dumps(body).encode("utf-8")
    api.request.json.return_value = body
    return api


def _note_mock(
    *,
    patient_id: str = PATIENT_ID,
    note_type: str = "Phone call",
    dos: dt.datetime | None = None,
    state: str | None = "NEW",
) -> MagicMock:
    note = MagicMock()
    note.dbid = 42
    note.patient.id = patient_id
    note.note_type_version.name = note_type
    note.datetime_of_service = dos or dt.datetime(2026, 3, 27, 10, 56, tzinfo=dt.timezone.utc)
    note.created = dt.datetime(2026, 3, 27, 10, 56, tzinfo=dt.timezone.utc)
    note.current_state = MagicMock(state=state) if state is not None else None
    return note


def _stub_note_get(mock_note_cls: MagicMock, note: MagicMock) -> None:
    mock_note_cls.objects.select_related.return_value.get.return_value = note


def _stub_note_missing(mock_note_cls: MagicMock) -> None:
    mock_note_cls.DoesNotExist = Exception
    mock_note_cls.objects.select_related.return_value.get.side_effect = (
        mock_note_cls.DoesNotExist()
    )


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.DiagnoseCommand")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_returns_note_type_and_dos_on_success(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_diagnose: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "Wegovy 0.25",
            "fdb_code": "606783",
            "sig": "Inject weekly",
            "days_supply": 28,
            "quantity_to_dispense": 4.0,
            "refills": 0,
            "representative_ndc": "00169452514",
            "ncpdp_quantity_qualifier_code": "C28254",
            "default_pharmacy_ncpdp_id": None,
        },
    }
    mock_prescribe.return_value.originate.return_value = _fake_effect({"fdb_code": "606783"})
    _stub_note_get(mock_note_cls, _note_mock())

    response_list = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()

    body = json.loads(response_list[0].content)
    assert body["success"] is True
    assert body["count"] == 1
    assert body["note_type"] == "Phone call"
    assert body["datetime_of_service"].startswith("2026-03-27")


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_rejects_note_not_belonging_to_patient(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock(patient_id="other-patient"))

    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)

    assert body["success"] is False
    assert "does not belong" in body["error"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_rejects_locked_note(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock(state="LKD"))

    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)

    assert body["success"] is False
    assert "locked" in body["error"].lower()
    assert body["state"] == "LKD"


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_rejects_signed_note(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock(state="SGN"))

    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)

    assert body["success"] is False
    assert body["state"] == "SGN"


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_requires_note_id(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    body = json.loads(_api({
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)
    assert body["success"] is False
    assert "note_id" in body["error"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_requires_patient_id(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)
    assert body["success"] is False
    assert "patient_id" in body["error"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.DiagnoseCommand")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_prescribes_medications_and_diagnoses_conditions(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_diagnose: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    mock_service = mock_service_cls.return_value
    mock_service.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "Wegovy 0.25",
            "fdb_code": "606783",
            "sig": "Inject weekly",
            "days_supply": 28,
            "quantity_to_dispense": 4.0,
            "refills": 0,
            "representative_ndc": "00169452514",
            "ncpdp_quantity_qualifier_code": "C28254",
            "default_pharmacy_ncpdp_id": None,
        },
        "custom_cond": {
            "id": "custom_cond",
            "favorite_type": "condition",
            "display_name": "Type 2 diabetes",
            "code": "E11.9",
        },
    }
    prescribe_effect = _fake_effect({"fdb_code": "606783", "sig": "Inject weekly"})
    diagnose_effect = _fake_effect({"icd10_code": "E11.9"})
    mock_prescribe.return_value.originate.return_value = prescribe_effect
    mock_diagnose.return_value.originate.return_value = diagnose_effect
    _stub_note_get(mock_note_cls, _note_mock())

    response_list = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med", "custom_cond"],
    }).post()

    body = json.loads(response_list[0].content)
    assert body["success"] is True
    assert body["count"] == 2
    mock_prescribe.assert_called_once()
    mock_diagnose.assert_called_once()
    prescribe_data = json.loads(prescribe_effect.payload)["data"]
    assert prescribe_data["fdb_code"] == "606783"
    assert "prescribe" not in prescribe_data
    assert prescribe_data["sig"] == "Inject weekly"
    diagnose_data = json.loads(diagnose_effect.payload)["data"]
    assert diagnose_data["icd10_code"] == "E11.9"
    assert "diagnose" not in diagnose_data


def test_post_rejects_missing_staff_header() -> None:
    response = _api(
        {"note_id": NOTE_UUID, "patient_id": PATIENT_ID, "favorite_ids": ["x"]},
        staff_id=None,
    ).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["error"] == "Staff ID not found"


def test_post_malformed_json_returns_400() -> None:
    api = InsertFavoritesAPI(MagicMock())
    api.request = MagicMock()
    api.request.headers = {"canvas-logged-in-user-id": "staff-uuid-1"}
    api.request.body = b"{not json"
    api.request.json.side_effect = ValueError("not json")

    response = api.post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Invalid JSON" in body["error"]


def test_post_requires_favorite_ids() -> None:
    response = _api({"note_id": NOTE_UUID, "patient_id": PATIENT_ID}).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "favorite_ids" in body["error"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_returns_404_when_note_does_not_exist(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_missing(mock_note_cls)

    response = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert body["error"] == "Note not found"


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_rejects_note_in_unrecognized_state(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock(state="DEL"))

    response = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "DEL" in body["error"]
    assert body["state"] == "DEL"


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_swallows_note_type_version_exceptions(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    note = _note_mock()
    type(note).note_type_version = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("relation missing"))
    )
    _stub_note_get(mock_note_cls, note)

    mock_service = mock_service_cls.return_value
    mock_service.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "Wegovy",
            "fdb_code": "1234",
            "sig": "weekly",
            "days_supply": 28,
            "quantity_to_dispense": 4.0,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "C28254",
            "default_pharmacy_ncpdp_id": None,
        }
    }
    mock_prescribe.return_value.originate.return_value = _fake_effect({"fdb_code": "1234"})

    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)

    assert body["success"] is True
    assert body["note_type"] == ""


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_skips_unknown_favorite_id(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {}

    response = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["missing"],
    }).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["skipped"] == ["missing"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_skips_medication_missing_fdb_code(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "Broken med",
            "fdb_code": "",
            "sig": "weekly",
        }
    }

    response = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Broken med" in body["skipped"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_skips_condition_missing_code(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_cond": {
            "id": "custom_cond",
            "favorite_type": "condition",
            "display_name": "Broken condition",
            "code": "",
        }
    }

    response = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_cond"],
    }).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "Broken condition" in body["skipped"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_skips_unknown_favorite_type(
    mock_service_cls: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_other": {
            "id": "custom_other",
            "favorite_type": "procedure",
            "display_name": "Wrong",
        }
    }

    response = _api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_other"],
    }).post()[0]
    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "custom_other" in body["skipped"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_includes_skipped_in_success_payload_when_some_succeed(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_ok": {
            "id": "custom_ok",
            "favorite_type": "medication",
            "display_name": "OK",
            "fdb_code": "1234",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": 1,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "default_pharmacy_ncpdp_id": None,
        }
    }
    mock_prescribe.return_value.originate.return_value = _fake_effect({"fdb_code": "1234"})

    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_ok", "missing"],
    }).post()[0].content)

    assert body["success"] is True
    assert body["count"] == 1
    assert body["skipped"] == ["missing"]


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_treats_missing_current_state_as_open(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    """A note with no current_state row should fall through to the empty-state branch."""
    _stub_note_get(mock_note_cls, _note_mock(state=None))
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "OK",
            "fdb_code": "1234",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": 1,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "default_pharmacy_ncpdp_id": None,
        }
    }
    mock_prescribe.return_value.originate.return_value = _fake_effect({"fdb_code": "1234"})

    body = json.loads(_api({
        "note_id": NOTE_UUID,
        "patient_id": PATIENT_ID,
        "favorite_ids": ["custom_med"],
    }).post()[0].content)
    assert body["success"] is True


def test_iso_helper_handles_none_and_fallback_string() -> None:
    assert _iso(None) == ""
    assert _iso("2026-01-02") == "2026-01-02"
    assert _iso(dt.datetime(2026, 1, 2)).startswith("2026-01-02")


def test_parse_body_falls_back_to_raw_decode_when_request_json_fails() -> None:
    request = MagicMock()
    request.json.side_effect = ValueError("nope")
    request.body = b'{"note_id": "abc"}'
    assert _parse_body(request) == {"note_id": "abc"}


# --- Ontology validation helpers ------------------------------------------


def _ontology_response(payload: Any) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    return response


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_medication_code_resolves_true_when_detail_has_content(mock_http: MagicMock) -> None:
    mock_http.get_json.return_value = _ontology_response(
        {"med_medication_id": 606783, "med_medication_description": "Wegovy 0.25"}
    )
    assert _medication_code_resolves("606783") is True


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_medication_code_resolves_false_when_detail_empty(mock_http: MagicMock) -> None:
    mock_http.get_json.return_value = _ontology_response({})
    assert _medication_code_resolves("000000") is False


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_medication_code_resolves_none_when_unreachable(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = OSError("boom")
    assert _medication_code_resolves("606783") is None


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_medication_code_resolves_none_on_unexpected_error(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = RuntimeError("bad day")
    assert _medication_code_resolves("606783") is None


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_medication_code_resolves_none_when_payload_not_a_dict(mock_http: MagicMock) -> None:
    mock_http.get_json.return_value = _ontology_response(["unexpected"])
    assert _medication_code_resolves("606783") is None


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_condition_code_resolves_none_on_unexpected_error(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = RuntimeError("bad day")
    assert _condition_code_resolves("E11.9") is None


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_condition_code_resolves_true_on_exact_match_ignoring_dot(mock_http: MagicMock) -> None:
    mock_http.get_json.return_value = _ontology_response(
        {"results": [{"icd10_code": "E11.9", "icd10_text": "Type 2 diabetes"}]}
    )
    assert _condition_code_resolves("E119") is True


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_condition_code_resolves_false_when_no_row_matches(mock_http: MagicMock) -> None:
    mock_http.get_json.return_value = _ontology_response(
        {"results": [{"icd10_code": "E10.9", "icd10_text": "Type 1 diabetes"}]}
    )
    assert _condition_code_resolves("E11.9") is False


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_condition_code_resolves_false_when_results_empty(mock_http: MagicMock) -> None:
    mock_http.get_json.return_value = _ontology_response({"results": []})
    assert _condition_code_resolves("Z999") is False


@patch("clinical_favorites.protocols.insert_api.ontologies_http")
def test_condition_code_resolves_none_when_unreachable(mock_http: MagicMock) -> None:
    mock_http.get_json.side_effect = OSError("boom")
    assert _condition_code_resolves("E11.9") is None


# --- Validation wired into the insert path --------------------------------


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_marks_medication_unresolved_and_does_not_originate(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "Retired med",
            "fdb_code": "000000",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": 1,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "default_pharmacy_ncpdp_id": None,
        }
    }

    with patch(
        "clinical_favorites.protocols.insert_api._medication_code_resolves",
        return_value=False,
    ):
        response = _api({
            "note_id": NOTE_UUID,
            "patient_id": PATIENT_ID,
            "favorite_ids": ["custom_med"],
        }).post()[0]

    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["success"] is False
    assert body["unresolved"][0]["code"] == "000000"
    assert body["unresolved"][0]["favorite_type"] == "medication"
    mock_prescribe.return_value.originate.assert_not_called()


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.DiagnoseCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_marks_condition_unresolved_and_does_not_originate(
    mock_service_cls: MagicMock,
    mock_diagnose: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_cond": {
            "id": "custom_cond",
            "favorite_type": "condition",
            "display_name": "Retired condition",
            "code": "Z999",
        }
    }

    with patch(
        "clinical_favorites.protocols.insert_api._condition_code_resolves",
        return_value=False,
    ):
        response = _api({
            "note_id": NOTE_UUID,
            "patient_id": PATIENT_ID,
            "favorite_ids": ["custom_cond"],
        }).post()[0]

    body = json.loads(response.content)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert body["unresolved"][0]["code"] == "Z999"
    mock_diagnose.return_value.originate.assert_not_called()


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_inserts_resolved_and_reports_unresolved_together(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_ok": {
            "id": "custom_ok",
            "favorite_type": "medication",
            "display_name": "Good med",
            "fdb_code": "606783",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": 1,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "default_pharmacy_ncpdp_id": None,
        },
        "custom_bad": {
            "id": "custom_bad",
            "favorite_type": "medication",
            "display_name": "Retired med",
            "fdb_code": "000000",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": 1,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "default_pharmacy_ncpdp_id": None,
        },
    }
    mock_prescribe.return_value.originate.return_value = _fake_effect({"fdb_code": "606783"})

    def _resolves(code: str) -> bool:
        return code != "000000"

    with patch(
        "clinical_favorites.protocols.insert_api._medication_code_resolves",
        side_effect=_resolves,
    ):
        body = json.loads(_api({
            "note_id": NOTE_UUID,
            "patient_id": PATIENT_ID,
            "favorite_ids": ["custom_ok", "custom_bad"],
        }).post()[0].content)

    assert body["success"] is True
    assert body["count"] == 1
    assert body["unresolved"][0]["code"] == "000000"


@patch("clinical_favorites.protocols.insert_api.Note")
@patch("clinical_favorites.protocols.insert_api.PrescribeCommand")
@patch("clinical_favorites.protocols.insert_api.FavoritesService")
def test_post_fails_open_and_inserts_when_validation_inconclusive(
    mock_service_cls: MagicMock,
    mock_prescribe: MagicMock,
    mock_note_cls: MagicMock,
) -> None:
    _stub_note_get(mock_note_cls, _note_mock())
    mock_service_cls.return_value.get_favorites_by_ids.return_value = {
        "custom_med": {
            "id": "custom_med",
            "favorite_type": "medication",
            "display_name": "Med",
            "fdb_code": "606783",
            "sig": "weekly",
            "days_supply": 30,
            "quantity_to_dispense": 1,
            "refills": 0,
            "representative_ndc": "ndc",
            "ncpdp_quantity_qualifier_code": "00",
            "default_pharmacy_ncpdp_id": None,
        }
    }
    mock_prescribe.return_value.originate.return_value = _fake_effect({"fdb_code": "606783"})

    with patch(
        "clinical_favorites.protocols.insert_api._medication_code_resolves",
        return_value=None,
    ):
        body = json.loads(_api({
            "note_id": NOTE_UUID,
            "patient_id": PATIENT_ID,
            "favorite_ids": ["custom_med"],
        }).post()[0].content)

    assert body["success"] is True
    assert body["count"] == 1
    assert "unresolved" not in body
