"""Tests for HospitalizationAPI endpoints."""
from __future__ import annotations

import json
from datetime import date
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient

from hospitalization_tracker.handlers.api import (
    HospitalizationAPI,
    HospitalizationSummaryCommand,
    HospitalizationWebSocket,
    _serialize_hospitalization,
)
from hospitalization_tracker.models import Hospitalization
from tests.conftest import HospitalizationFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    json_body: dict | None = None,
    query_params: dict | None = None,
) -> MagicMock:
    """Build a minimal mock request object."""
    req = MagicMock()
    req.query_params = query_params or {}
    req.json.return_value = json_body or {}
    return req


def _make_api(request: MagicMock) -> HospitalizationAPI:
    """Instantiate HospitalizationAPI bypassing authentication."""
    api = MagicMock(spec=HospitalizationAPI)
    api.request = request
    return api


# ---------------------------------------------------------------------------
# GET /app/form
# ---------------------------------------------------------------------------


def test_get_form_missing_params_returns_400() -> None:
    """Returns 400 when patient_id or note_id is absent."""
    req = _make_request(query_params={})
    api = _make_api(req)
    result = HospitalizationAPI.get_form(api)
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_form_only_patient_id_returns_400() -> None:
    """Returns 400 when note_id is missing."""
    req = _make_request(query_params={"patient_id": "p-123"})
    api = _make_api(req)
    result = HospitalizationAPI.get_form(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_get_form_returns_html_response() -> None:
    """Returns an HTMLResponse when both patient_id and note_id are present."""
    req = _make_request(query_params={"patient_id": "p-123", "note_id": "n-456"})
    api = _make_api(req)
    with patch(
        "hospitalization_tracker.handlers.api.render_to_string",
        return_value="<html>form</html>",
    ) as mock_render:
        result = HospitalizationAPI.get_form(api)

    mock_render.assert_called_once()
    assert len(result) == 1
    # HTMLResponse has content attribute
    assert result[0].content == b"<html>form</html>"


# ---------------------------------------------------------------------------
# GET /hospitalizations
# ---------------------------------------------------------------------------


def test_list_hospitalizations_missing_patient_id_returns_400() -> None:
    """Returns 400 when patient_id query param is absent."""
    req = _make_request(query_params={})
    api = _make_api(req)
    result = HospitalizationAPI.list_hospitalizations(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


@patch("hospitalization_tracker.handlers.api.Hospitalization.objects")
def test_list_hospitalizations_returns_json(mock_objects: MagicMock) -> None:
    """Returns a JSON list of hospitalizations for the given patient."""
    mock_h = MagicMock(spec=Hospitalization)
    mock_h.dbid = 1
    mock_h.admission_date = date(2024, 3, 1)
    mock_h.discharge_date = date(2024, 3, 8)
    mock_h.hospital_name = "City Hospital"
    mock_h.reason_for_admission = "Chest pain"
    mock_h.principal_diagnosis = "STEMI"
    mock_h.icu_stay = False
    mock_h.icu_duration_days = None
    mock_h.discharge_disposition = "Home"
    mock_h.readmission_within_30_days = False
    mock_h.treating_physician = "Dr. A"
    mock_h.notes = ""
    mock_h.length_of_stay_days = 7
    mock_h.created_at = MagicMock()
    mock_h.created_at.isoformat.return_value = "2024-03-01T00:00:00"

    mock_objects.filter.return_value.order_by.return_value = [mock_h]

    req = _make_request(query_params={"patient_id": "patient-uuid-123"})
    api = _make_api(req)
    result = HospitalizationAPI.list_hospitalizations(api)

    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.OK
    data = json.loads(result[0].content)
    assert "hospitalizations" in data
    assert len(data["hospitalizations"]) == 1
    assert data["hospitalizations"][0]["hospital_name"] == "City Hospital"
    assert data["hospitalizations"][0]["length_of_stay_days"] == 7


# ---------------------------------------------------------------------------
# POST /hospitalizations — validation errors
# ---------------------------------------------------------------------------


def test_create_missing_patient_id_returns_400() -> None:
    """Returns 400 when patient_id is absent from the body."""
    req = _make_request(json_body={"note_id": "n-1", "admission_date": "2024-03-01", "hospital_name": "H", "reason_for_admission": "R"})
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_missing_note_id_returns_400() -> None:
    """Returns 400 when note_id is absent from the body."""
    req = _make_request(json_body={"patient_id": "p-1", "admission_date": "2024-03-01", "hospital_name": "H", "reason_for_admission": "R"})
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_missing_admission_date_returns_400() -> None:
    """Returns 400 when admission_date is absent."""
    req = _make_request(json_body={"patient_id": "p-1", "note_id": "n-1", "hospital_name": "H", "reason_for_admission": "R"})
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_missing_hospital_name_returns_400() -> None:
    """Returns 400 when hospital_name is absent."""
    req = _make_request(json_body={"patient_id": "p-1", "note_id": "n-1", "admission_date": "2024-03-01", "reason_for_admission": "R"})
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


def test_create_missing_reason_returns_400() -> None:
    """Returns 400 when reason_for_admission is absent."""
    req = _make_request(json_body={"patient_id": "p-1", "note_id": "n-1", "admission_date": "2024-03-01", "hospital_name": "H"})
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.BAD_REQUEST


@patch("hospitalization_tracker.handlers.api.Patient.objects")
def test_create_patient_not_found_returns_404(mock_patient_objects: MagicMock) -> None:
    """Returns 404 when patient does not exist."""
    mock_patient_objects.get.side_effect = Patient.DoesNotExist()
    req = _make_request(
        json_body={
            "patient_id": "nonexistent",
            "note_id": "n-1",
            "admission_date": "2024-03-01",
            "hospital_name": "H",
            "reason_for_admission": "R",
        }
    )
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.NOT_FOUND


@patch("hospitalization_tracker.handlers.api.Note.objects")
@patch("hospitalization_tracker.handlers.api.Patient.objects")
def test_create_note_not_found_returns_404(
    mock_patient_objects: MagicMock, mock_note_objects: MagicMock
) -> None:
    """Returns 404 when the note does not exist."""
    mock_patient_objects.get.return_value = MagicMock()
    mock_note_objects.get.side_effect = Note.DoesNotExist()
    req = _make_request(
        json_body={
            "patient_id": "p-1",
            "note_id": "nonexistent",
            "admission_date": "2024-03-01",
            "hospital_name": "H",
            "reason_for_admission": "R",
        }
    )
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)
    assert result[0].status_code == HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# POST /hospitalizations — happy path (mocked)
# ---------------------------------------------------------------------------


@patch("hospitalization_tracker.handlers.api.Hospitalization")
@patch("hospitalization_tracker.handlers.api.render_to_string")
@patch("hospitalization_tracker.handlers.api.Note.objects")
@patch("hospitalization_tracker.handlers.api.Patient.objects")
def test_create_hospitalization_success(
    mock_patient_objects: MagicMock,
    mock_note_objects: MagicMock,
    mock_render: MagicMock,
    mock_hosp_class: MagicMock,
) -> None:
    """Returns 201 + command originate effect on valid submission."""
    mock_patient = MagicMock()
    mock_patient_objects.get.return_value = mock_patient

    mock_note = MagicMock()
    mock_note.id = "note-uuid-000"
    mock_note_objects.get.return_value = mock_note

    # Mock the Hospitalization constructor and instance
    mock_hosp_instance = MagicMock()
    mock_hosp_instance.dbid = 99
    mock_hosp_class.return_value = mock_hosp_instance
    mock_hosp_class.objects.filter.return_value.order_by.return_value = []

    mock_render.return_value = "<html>table</html>"

    req = _make_request(
        json_body={
            "patient_id": "patient-uuid-123",
            "note_id": "note-uuid-000",
            "admission_date": "2024-05-01",
            "hospital_name": "General Hospital",
            "reason_for_admission": "Chest pain",
            "principal_diagnosis": "STEMI",
            "icu_stay": True,
            "icu_duration_days": 3,
            "discharge_date": "2024-05-10",
            "discharge_disposition": "Home",
            "readmission_within_30_days": False,
            "treating_physician": "Dr. A",
            "notes": "Stable on discharge",
        }
    )
    api = _make_api(req)
    result = HospitalizationAPI.create_hospitalization(api)

    # Three items: command.originate() + Broadcast + JSONResponse
    assert len(result) == 3
    json_response = result[2]
    assert json_response.status_code == HTTPStatus.CREATED
    data = json.loads(json_response.content)
    assert data["success"] is True


# ---------------------------------------------------------------------------
# POST /hospitalizations — integration test (real DB)
# ---------------------------------------------------------------------------


@pytest.mark.integtest
def test_create_hospitalization_integration() -> None:
    """End-to-end: creates a Hospitalization record in the database from API logic."""
    from canvas_sdk.test_utils.factories import NoteFactory

    patient = PatientFactory.create()
    note = NoteFactory.create(patient=patient)

    req = _make_request(
        json_body={
            "patient_id": str(patient.id),
            "note_id": str(note.id),
            "admission_date": "2024-05-01",
            "hospital_name": "Metro Hospital",
            "reason_for_admission": "Pneumonia",
            "icu_stay": False,
        }
    )
    api = _make_api(req)

    with patch(
        "hospitalization_tracker.handlers.api.render_to_string",
        return_value="<html></html>",
    ):
        result = HospitalizationAPI.create_hospitalization(api)

    # Three effects: originate command + Broadcast + JSON response
    assert len(result) == 3
    data = json.loads(result[2].content)
    assert data["success"] is True

    # Verify DB record
    h = Hospitalization.objects.get(dbid=data["id"])
    assert h.hospital_name == "Metro Hospital"
    assert h.reason_for_admission == "Pneumonia"
    assert h.patient.id == patient.id


@pytest.mark.integtest
def test_list_hospitalizations_integration() -> None:
    """End-to-end: list endpoint returns hospitalizations from the database."""
    patient = PatientFactory.create()
    HospitalizationFactory.create(patient=patient, hospital_name="Hospital A")
    HospitalizationFactory.create(patient=patient, hospital_name="Hospital B")

    req = _make_request(query_params={"patient_id": str(patient.id)})
    api = _make_api(req)
    result = HospitalizationAPI.list_hospitalizations(api)

    assert result[0].status_code == HTTPStatus.OK
    data = json.loads(result[0].content)
    assert len(data["hospitalizations"]) == 2
    hospital_names = {h["hospital_name"] for h in data["hospitalizations"]}
    assert hospital_names == {"Hospital A", "Hospital B"}


# ---------------------------------------------------------------------------
# _serialize_hospitalization helper
# ---------------------------------------------------------------------------


def test_serialize_hospitalization_includes_all_fields() -> None:
    """Serializer returns all expected fields."""
    h = MagicMock(spec=Hospitalization)
    h.dbid = 42
    h.admission_date = date(2024, 1, 1)
    h.discharge_date = date(2024, 1, 10)
    h.hospital_name = "Test Hospital"
    h.reason_for_admission = "Stroke"
    h.principal_diagnosis = "Ischemic stroke"
    h.icu_stay = True
    h.icu_duration_days = 4
    h.discharge_disposition = "Rehab"
    h.readmission_within_30_days = False
    h.treating_physician = "Dr. B"
    h.notes = "Stable"
    h.length_of_stay_days = 9
    h.created_at = MagicMock()
    h.created_at.isoformat.return_value = "2024-01-01T00:00:00"

    result = _serialize_hospitalization(h)
    assert result["id"] == 42
    assert result["hospital_name"] == "Test Hospital"
    assert result["icu_stay"] is True
    assert result["icu_duration_days"] == 4
    assert result["length_of_stay_days"] == 9
    assert result["admission_date"] == "2024-01-01"
    assert result["discharge_date"] == "2024-01-10"


# ---------------------------------------------------------------------------
# HospitalizationSummaryCommand schema key
# ---------------------------------------------------------------------------


def test_custom_command_schema_key() -> None:
    """HospitalizationSummaryCommand uses the correct schema_key."""
    cmd = HospitalizationSummaryCommand(content="<p>test</p>")
    assert cmd.schema_key == "hospitalizationSummary"


# ---------------------------------------------------------------------------
# GET /section
# ---------------------------------------------------------------------------


def test_get_section_missing_patient_id_returns_400() -> None:
    """GET /section without patient_id returns 400."""
    req = _make_request(query_params={})
    api = _make_api(req)
    result = HospitalizationAPI.get_section(api)
    assert len(result) == 1
    assert result[0].status_code == HTTPStatus.BAD_REQUEST
    assert b"patient_id" in result[0].content


@patch("hospitalization_tracker.handlers.api.render_to_string", return_value="<html>section</html>")
@patch("hospitalization_tracker.handlers.api.Hospitalization.objects")
def test_get_section_returns_html(mock_objects: MagicMock, mock_render: MagicMock) -> None:
    """GET /section with patient_id returns rendered HTML."""
    mock_objects.filter.return_value.order_by.return_value = []
    req = _make_request(query_params={"patient_id": "patient-abc"})
    api = _make_api(req)
    result = HospitalizationAPI.get_section(api)
    assert len(result) == 1
    assert b"section" in result[0].content
    mock_render.assert_called_once()
    ctx = mock_render.call_args[0][1]
    assert ctx["patient_id"] == "patient-abc"


# ---------------------------------------------------------------------------
# HospitalizationWebSocket
# ---------------------------------------------------------------------------


def test_websocket_authenticate_returns_true() -> None:
    """HospitalizationWebSocket.authenticate() always returns True (Canvas session auth)."""
    mock_event = MagicMock()
    mock_event.context = {"channel_name": "test-channel", "headers": []}
    ws = HospitalizationWebSocket(event=mock_event)
    assert ws.authenticate() is True
