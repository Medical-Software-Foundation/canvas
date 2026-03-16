"""Tests for the SimpleAPI endpoints — patient effect building logic."""

from __future__ import annotations

import datetime
import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from canvas_sdk.effects.patient import Patient, PatientAddress, PatientContactPoint, PatientExternalIdentifier
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.v1.data.common import AddressUse, ContactPointSystem, ContactPointUse, PersonSex

from patient_csv_loader.apps.api import (
    PatientCSVAPI,
    _build_address,
    _build_contact_points,
    _build_external_identifiers,
    _build_patient_effect,
)


def _parse_json_response(resp: JSONResponse) -> Any:
    """Parse the JSON content of a JSONResponse."""
    return json.loads(resp.content)


def _make_valid_data(**overrides: str | None) -> dict[str, str | None]:
    """Return a minimal valid row data dict."""
    data: dict[str, str | None] = {
        "first_name": "Jane",
        "last_name": "Doe",
        "birthdate": "1985-03-15",
        "sex_at_birth": "F",
        "phone": "5551234567",
    }
    data.update(overrides)
    return data


# ─── Contact point building ───


class TestBuildContactPoints:
    def test_phone_only(self) -> None:
        contacts = _build_contact_points(_make_valid_data())
        assert len(contacts) == 1
        assert contacts[0].system == ContactPointSystem.PHONE
        assert contacts[0].value == "5551234567"
        assert contacts[0].use == ContactPointUse.MOBILE
        assert contacts[0].rank == 1

    def test_with_additional_contact(self) -> None:
        data = _make_valid_data(
            contact_1_system="email",
            contact_1_value="jane@example.com",
        )
        contacts = _build_contact_points(data)
        assert len(contacts) == 2
        assert contacts[1].system == ContactPointSystem.EMAIL
        assert contacts[1].value == "jane@example.com"
        assert contacts[1].use == ContactPointUse.HOME  # default
        assert contacts[1].rank == 2  # default for slot 1

    def test_contact_with_custom_use_and_rank(self) -> None:
        data = _make_valid_data(
            contact_1_system="phone",
            contact_1_value="5559999876",
            contact_1_use="work",
            contact_1_rank="5",
            contact_1_has_consent="true",
        )
        contacts = _build_contact_points(data)
        assert len(contacts) == 2
        assert contacts[1].use == ContactPointUse.WORK
        assert contacts[1].rank == 5
        assert contacts[1].has_consent is True

    def test_two_additional_contacts(self) -> None:
        data = _make_valid_data(
            contact_1_system="email",
            contact_1_value="jane@example.com",
            contact_2_system="fax",
            contact_2_value="5550001234",
        )
        contacts = _build_contact_points(data)
        assert len(contacts) == 3
        assert contacts[2].system == ContactPointSystem.FAX
        assert contacts[2].rank == 3  # default for slot 2

    def test_empty_contact_slot_skipped(self) -> None:
        data = _make_valid_data(contact_1_system="", contact_1_value="")
        contacts = _build_contact_points(data)
        assert len(contacts) == 1  # only the required phone


# ─── Address building ───


class TestBuildAddress:
    def test_no_address(self) -> None:
        assert _build_address(_make_valid_data()) is None

    def test_complete_address(self) -> None:
        data = _make_valid_data(
            address_line1="123 Main St",
            address_line2="Apt 4B",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701",
            address_country="US",
            address_use="work",
        )
        addr = _build_address(data)
        assert addr is not None
        assert addr.line1 == "123 Main St"
        assert addr.line2 == "Apt 4B"
        assert addr.city == "Springfield"
        assert addr.state_code == "IL"
        assert addr.postal_code == "62701"
        assert addr.country == "US"
        assert addr.use == AddressUse.WORK

    def test_address_defaults_to_home(self) -> None:
        data = _make_valid_data(
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701",
            address_country="US",
        )
        addr = _build_address(data)
        assert addr is not None
        assert addr.use == AddressUse.HOME


# ─── External identifiers ───


class TestBuildExternalIdentifiers:
    def test_no_identifiers(self) -> None:
        ids = _build_external_identifiers(_make_valid_data())
        assert ids == []

    def test_one_identifier(self) -> None:
        data = _make_valid_data(
            external_id_1_system="http://old-ehr.com",
            external_id_1_value="PAT-001",
        )
        ids = _build_external_identifiers(data)
        assert len(ids) == 1
        assert ids[0].system == "http://old-ehr.com"
        assert ids[0].value == "PAT-001"

    def test_multiple_identifiers(self) -> None:
        data = _make_valid_data(
            external_id_1_system="http://ehr1.com",
            external_id_1_value="ID1",
            external_id_3_system="http://ehr3.com",
            external_id_3_value="ID3",
        )
        ids = _build_external_identifiers(data)
        assert len(ids) == 2


# ─── Patient effect building ───


class TestBuildPatientEffect:
    def test_minimal_patient_effect(self) -> None:
        effect = _build_patient_effect(_make_valid_data())
        assert effect is not None
        assert effect.type is not None

    def test_patient_with_optional_fields(self) -> None:
        data = _make_valid_data(
            middle_name="Marie",
            prefix="Ms.",
            suffix="Jr.",
            nickname="Janie",
            social_security_number="123-45-6789",
            administrative_note="Test note",
            clinical_note="No allergies",
        )
        effect = _build_patient_effect(data)
        assert effect is not None

    def test_patient_with_all_fields(self) -> None:
        data = _make_valid_data(
            middle_name="Marie",
            address_line1="123 Main St",
            address_city="Springfield",
            address_state_code="IL",
            address_postal_code="62701",
            address_country="US",
            contact_1_system="email",
            contact_1_value="jane@example.com",
            external_id_1_system="http://old-ehr.com",
            external_id_1_value="PAT-001",
        )
        effect = _build_patient_effect(data)
        assert effect is not None


# ─── Endpoint handler tests ───


def _make_api_instance() -> PatientCSVAPI:
    """Create a PatientCSVAPI with mocked request and secrets."""
    api_instance = PatientCSVAPI.__new__(PatientCSVAPI)
    api_instance.request = MagicMock()
    api_instance.secrets = {}
    return api_instance


class TestValidateCSVEndpoint:
    def test_no_file_returns_400(self) -> None:
        api_instance = _make_api_instance()
        mock_form_data = MagicMock()
        mock_form_data.get.return_value = None
        api_instance.request.form_data.return_value = mock_form_data

        result = api_instance.validate_csv()

        assert len(result) == 1
        assert isinstance(result[0], JSONResponse)
        body = _parse_json_response(result[0])
        assert "error" in body
        assert mock_form_data.mock_calls == [call.get("file")]

    def test_non_file_part_returns_400(self) -> None:
        api_instance = _make_api_instance()
        mock_file_part = MagicMock()
        mock_file_part.is_file.return_value = False
        mock_form_data = MagicMock()
        mock_form_data.get.return_value = mock_file_part
        api_instance.request.form_data.return_value = mock_form_data

        result = api_instance.validate_csv()

        assert len(result) == 1
        assert isinstance(result[0], JSONResponse)
        assert mock_file_part.mock_calls == [call.is_file()]

    def test_valid_csv_no_s3_secrets(self) -> None:
        api_instance = _make_api_instance()
        csv_bytes = b"first_name,last_name,birthdate,sex_at_birth,phone\nJane,Doe,1985-03-15,F,5551234567"
        mock_file_part = MagicMock()
        mock_file_part.is_file.return_value = True
        mock_file_part.content = csv_bytes
        mock_form_data = MagicMock()
        mock_form_data.get.return_value = mock_file_part
        api_instance.request.form_data.return_value = mock_form_data

        with patch("patient_csv_loader.apps.api.log") as mock_log:
            result = api_instance.validate_csv()

            assert mock_log.mock_calls == [
                call.warning("Patient CSV Loader: S3 secrets not configured, skipping audit upload"),
            ]

        assert len(result) == 1
        body = _parse_json_response(result[0])
        assert body["total_rows"] == 1
        assert body["valid_count"] == 1
        assert body["error_count"] == 0
        assert len(body["warnings"]) == 1
        assert "not configured" in body["warnings"][0]

    def test_valid_csv_s3_upload_success(self) -> None:
        api_instance = _make_api_instance()
        api_instance.secrets = {
            "S3_BUCKET_NAME": "my-bucket",
            "AWS_ACCESS_KEY_ID": "AKID",
            "AWS_SECRET_ACCESS_KEY": "secret",
        }
        csv_bytes = b"first_name,last_name,birthdate,sex_at_birth,phone\nJane,Doe,1985-03-15,F,5551234567"
        mock_file_part = MagicMock()
        mock_file_part.is_file.return_value = True
        mock_file_part.content = csv_bytes
        mock_file_part.filename = "patients.csv"
        mock_form_data = MagicMock()
        mock_form_data.get.return_value = mock_file_part
        api_instance.request.form_data.return_value = mock_form_data

        with patch("patient_csv_loader.apps.api.upload_csv_to_s3", return_value=True) as mock_upload:
            result = api_instance.validate_csv()

            assert mock_upload.mock_calls == [
                call(
                    csv_content=csv_bytes.decode("utf-8-sig"),
                    filename="patients.csv",
                    bucket="my-bucket",
                    access_key_id="AKID",
                    secret_access_key="secret",
                ),
            ]

        body = _parse_json_response(result[0])
        assert body["warnings"] == []

    def test_valid_csv_s3_upload_failure_warns(self) -> None:
        api_instance = _make_api_instance()
        api_instance.secrets = {
            "S3_BUCKET_NAME": "my-bucket",
            "AWS_ACCESS_KEY_ID": "AKID",
            "AWS_SECRET_ACCESS_KEY": "secret",
        }
        csv_bytes = b"first_name,last_name,birthdate,sex_at_birth,phone\nJane,Doe,1985-03-15,F,5551234567"
        mock_file_part = MagicMock()
        mock_file_part.is_file.return_value = True
        mock_file_part.content = csv_bytes
        mock_file_part.filename = "patients.csv"
        mock_form_data = MagicMock()
        mock_form_data.get.return_value = mock_file_part
        api_instance.request.form_data.return_value = mock_form_data

        with patch("patient_csv_loader.apps.api.upload_csv_to_s3", return_value=False) as mock_upload:
            result = api_instance.validate_csv()

            assert len(mock_upload.mock_calls) == 1

        body = _parse_json_response(result[0])
        assert len(body["warnings"]) == 1
        assert "Unable to save" in body["warnings"][0]

    def test_error_rows_included_in_response(self) -> None:
        api_instance = _make_api_instance()
        csv_bytes = b"first_name,last_name,birthdate,sex_at_birth,phone\n,Doe,1985-03-15,F,5551234567"
        mock_file_part = MagicMock()
        mock_file_part.is_file.return_value = True
        mock_file_part.content = csv_bytes
        mock_form_data = MagicMock()
        mock_form_data.get.return_value = mock_file_part
        api_instance.request.form_data.return_value = mock_form_data

        result = api_instance.validate_csv()

        body = _parse_json_response(result[0])
        assert body["error_count"] == 1
        assert body["valid_count"] == 0
        assert len(body["error_rows"]) == 1
        assert body["error_rows"][0]["row_number"] == 2


class TestCreatePatientsEndpoint:
    def test_no_rows_returns_400(self) -> None:
        api_instance = _make_api_instance()
        api_instance.request.json.return_value = {"rows": []}

        result = api_instance.create_patients()

        assert len(result) == 1
        assert isinstance(result[0], JSONResponse)
        assert api_instance.request.mock_calls == [call.json()]

    def test_creates_patient_effects(self) -> None:
        api_instance = _make_api_instance()
        api_instance.request.json.return_value = {
            "rows": [
                {"data": _make_valid_data()},
                {"data": _make_valid_data(first_name="John", last_name="Smith")},
            ]
        }

        with patch("patient_csv_loader.apps.api.log") as mock_log:
            result = api_instance.create_patients()

            assert mock_log.mock_calls == [
                call.info("Patient CSV Loader: submitting 2 patient create effects"),
            ]

        # 2 patient effects + 1 JSON response
        assert len(result) == 3
        assert isinstance(result[2], JSONResponse)
        body = _parse_json_response(result[2])
        assert body["submitted_count"] == 2
        assert body["total_requested"] == 2

    def test_handles_build_error_gracefully(self) -> None:
        api_instance = _make_api_instance()
        api_instance.request.json.return_value = {
            "rows": [
                {"data": _make_valid_data()},
                {"data": {"first_name": "Bad"}},  # missing required fields
            ]
        }

        with patch("patient_csv_loader.apps.api.log") as mock_log:
            result = api_instance.create_patients()

            # Should log error for the bad row
            assert any("Failed to build patient effect" in str(c) for c in mock_log.mock_calls)

        # 1 patient effect + 1 JSON response (bad row skipped)
        assert len(result) == 2
        body = _parse_json_response(result[1])
        assert body["submitted_count"] == 1
        assert body["total_requested"] == 2


class TestDownloadTemplateEndpoint:
    def test_returns_csv_response(self) -> None:
        api_instance = _make_api_instance()

        result = api_instance.download_template()

        assert len(result) == 1
        assert isinstance(result[0], Response)

    def test_template_has_csv_headers(self) -> None:
        api_instance = _make_api_instance()

        result = api_instance.download_template()

        resp = result[0]
        assert resp.headers["Content-Type"] == "text/csv"
        assert "patient_load_template.csv" in resp.headers["Content-Disposition"]
