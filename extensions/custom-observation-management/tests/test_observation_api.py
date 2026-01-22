"""Tests for the ObservationAPI SimpleAPI handler."""

import json
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch, call

import pytest

from custom_observation_management.protocols.my_protocol import ObservationAPI


class TestGetObservationsForPatient:
    """Tests for the GET /observations endpoint."""

    def test_get_observations_with_patient_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by patient_id."""
        mock_request.query_params = {"patient_id": "patient-uuid-123"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
                with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                    mock_patient_class.objects.filter.return_value.exists.return_value = True
                    mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                    mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                        "id": "note-uuid-123",
                        "datetime_of_service": None,
                    }

                    result = handler.get_observations_for_patient()

                    mock_patient_class.objects.filter.assert_called_with(id="patient-uuid-123")
                    assert len(result) == 1
                    response_data = json.loads(result[0].content)
                    assert isinstance(response_data, list)

    def test_get_observations_patient_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when patient_id doesn't exist."""
        mock_request.query_params = {"patient_id": "nonexistent-patient"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = False

            result = handler.get_observations_for_patient()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.NOT_FOUND
            assert "Patient not found" in response_data["error"]

    def test_get_observations_with_name_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by name."""
        mock_request.query_params = {"name": "Blood Pressure"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_with_category_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by category (comma-separated)."""
        mock_request.query_params = {"category": "vital-signs,laboratory"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_with_datetime_start_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by effective_datetime_start."""
        mock_request.query_params = {"effective_datetime_start": "2024-01-01T00:00:00Z"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_with_datetime_end_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by effective_datetime_end."""
        mock_request.query_params = {"effective_datetime_end": "2024-12-31T23:59:59Z"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_with_datetime_range_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by datetime range (start and end)."""
        mock_request.query_params = {
            "effective_datetime_start": "2024-01-01T00:00:00Z",
            "effective_datetime_end": "2024-12-31T23:59:59Z",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_invalid_datetime_start(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when effective_datetime_start is invalid."""
        mock_request.query_params = {"effective_datetime_start": "not-a-date"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        result = handler.get_observations_for_patient()

        assert len(result) == 1
        response_data = json.loads(result[0].content)
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid effective_datetime_start format" in response_data["error"]

    def test_get_observations_invalid_datetime_end(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when effective_datetime_end is invalid."""
        mock_request.query_params = {"effective_datetime_end": "invalid-date"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        result = handler.get_observations_for_patient()

        assert len(result) == 1
        response_data = json.loads(result[0].content)
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        assert "Invalid effective_datetime_end format" in response_data["error"]

    def test_get_observations_with_note_dbid_filter(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering observations by note_dbid."""
        mock_request.query_params = {"note_dbid": "12345"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
            with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
                mock_note_class.objects.filter.return_value.exists.return_value = True
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observations_note_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_dbid doesn't exist."""
        mock_request.query_params = {"note_dbid": "99999"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
            mock_note_class.objects.filter.return_value.exists.return_value = False

            result = handler.get_observations_for_patient()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.NOT_FOUND
            assert "Note not found" in response_data["error"]

    def test_get_observations_no_filters_returns_all(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that no filters returns all non-deleted observations."""
        mock_request.query_params = {}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                # Verify exclude was called with deleted and entered_in_error filters
                mock_obs_class.objects.exclude.assert_called_once()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK


class TestGetSingleObservation:
    """Tests for the GET /observation/<observation_id> endpoint."""

    def test_get_observation_success(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test successfully retrieving a single observation."""
        mock_request.path_params = {"observation_id": "obs-uuid-123"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_obs_class.objects.get.return_value = mock_observation
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observation()

                mock_obs_class.objects.get.assert_called_with(id="obs-uuid-123")
                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_get_observation_missing_id(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when observation_id is missing."""
        mock_request.path_params = {}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        result = handler.get_observation()

        assert len(result) == 1
        response_data = json.loads(result[0].content)
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        assert "Observation ID is required" in response_data["error"]


class TestCreateObservation:
    """Tests for the POST /observation endpoint."""

    def test_create_observation_success(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test successfully creating an observation."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_effect_instance = MagicMock()
                mock_effect_class.return_value = mock_effect_instance

                result = handler.create_observation()

                mock_effect_class.assert_called_once()
                assert len(result) == 2
                assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_missing_patient_id(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when patient_id is missing."""
        mock_request.json.return_value = {
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        result = handler.create_observation()

        assert len(result) == 1
        response_data = json.loads(result[0].content)
        assert result[0].status_code == HTTPStatus.BAD_REQUEST
        assert "'patient_id' is required" in response_data["errors"]

    def test_create_observation_missing_name(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when name is missing."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "effective_datetime": "2024-06-15T10:30:00Z",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert "'name' is required" in response_data["errors"]

    def test_create_observation_invalid_datetime(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when effective_datetime is invalid."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "not-a-date",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("Invalid effective_datetime format" in e for e in response_data["errors"])

    def test_create_observation_patient_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when patient doesn't exist."""
        mock_request.json.return_value = {
            "patient_id": "nonexistent-patient",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = False

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert "Patient not found" in response_data["errors"]

    def test_create_observation_with_optional_fields(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with all optional fields."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "category": "vital-signs",
            "value": "120/80",
            "units": "mmHg",
            "note_id": 12345,
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                    mock_patient_class.objects.filter.return_value.exists.return_value = True
                    mock_note_class.objects.filter.return_value.exists.return_value = True
                    mock_effect_instance = MagicMock()
                    mock_effect_class.return_value = mock_effect_instance

                    result = handler.create_observation()

                    call_kwargs = mock_effect_class.call_args.kwargs
                    assert call_kwargs["category"] == "vital-signs"
                    assert call_kwargs["value"] == "120/80"
                    assert call_kwargs["units"] == "mmHg"
                    assert call_kwargs["note_id"] == 12345
                    assert len(result) == 2
                    assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_category_list(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with category as a list."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "category": ["vital-signs", "laboratory"],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_effect_instance = MagicMock()
                mock_effect_class.return_value = mock_effect_instance

                result = handler.create_observation()

                call_kwargs = mock_effect_class.call_args.kwargs
                assert call_kwargs["category"] == ["vital-signs", "laboratory"]
                assert len(result) == 2
                assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_codings(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with FHIR codings."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "codings": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood pressure panel",
                }
            ],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_effect_instance = MagicMock()
                mock_effect_class.return_value = mock_effect_instance

                result = handler.create_observation()

                call_kwargs = mock_effect_class.call_args.kwargs
                assert call_kwargs["codings"] is not None
                assert len(call_kwargs["codings"]) == 1
                assert call_kwargs["codings"][0].code == "85354-9"
                assert call_kwargs["codings"][0].system == "http://loinc.org"
                assert len(result) == 2
                assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_components(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with components (e.g., systolic/diastolic)."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "components": [
                {
                    "name": "Systolic",
                    "value_quantity": "120",
                    "value_quantity_unit": "mmHg",
                },
                {
                    "name": "Diastolic",
                    "value_quantity": "80",
                    "value_quantity_unit": "mmHg",
                },
            ],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_effect_instance = MagicMock()
                mock_effect_class.return_value = mock_effect_instance

                result = handler.create_observation()

                call_kwargs = mock_effect_class.call_args.kwargs
                assert call_kwargs["components"] is not None
                assert len(call_kwargs["components"]) == 2
                assert call_kwargs["components"][0].name == "Systolic"
                assert call_kwargs["components"][0].value_quantity == "120"
                assert call_kwargs["components"][1].name == "Diastolic"
                assert len(result) == 2
                assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_components_and_codings(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with components that have codings."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "components": [
                {
                    "name": "Systolic",
                    "value_quantity": "120",
                    "value_quantity_unit": "mmHg",
                    "codings": [
                        {
                            "system": "http://loinc.org",
                            "code": "8480-6",
                            "display": "Systolic blood pressure",
                        }
                    ],
                },
            ],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_effect_instance = MagicMock()
                mock_effect_class.return_value = mock_effect_instance

                result = handler.create_observation()

                call_kwargs = mock_effect_class.call_args.kwargs
                assert call_kwargs["components"] is not None
                assert call_kwargs["components"][0].codings is not None
                assert call_kwargs["components"][0].codings[0].code == "8480-6"
                assert len(result) == 2
                assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_value_codings(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with value codings."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Smoking Status",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "value_codings": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "266919005",
                    "display": "Never smoked tobacco",
                }
            ],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_effect_instance = MagicMock()
                mock_effect_class.return_value = mock_effect_instance

                result = handler.create_observation()

                call_kwargs = mock_effect_class.call_args.kwargs
                assert call_kwargs["value_codings"] is not None
                assert len(call_kwargs["value_codings"]) == 1
                assert call_kwargs["value_codings"][0].code == "266919005"
                assert len(result) == 2
                assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_is_member_of(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with parent observation reference."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Systolic Component",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "is_member_of_id": "parent-obs-uuid-456",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
                with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                    mock_patient_class.objects.filter.return_value.exists.return_value = True
                    mock_obs_class.objects.filter.return_value.exists.return_value = True
                    mock_effect_instance = MagicMock()
                    mock_effect_class.return_value = mock_effect_instance

                    result = handler.create_observation()

                    call_kwargs = mock_effect_class.call_args.kwargs
                    assert call_kwargs["is_member_of_id"] == "parent-obs-uuid-456"
                    assert len(result) == 2
                    assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_invalid_codings_missing_required(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when codings are missing required fields."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "codings": [
                {"system": "http://loinc.org"}  # Missing code and display
            ],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("codings[0].code" in e for e in response_data["errors"])
            assert any("codings[0].display" in e for e in response_data["errors"])

    def test_create_observation_invalid_components_missing_required(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when components are missing required fields."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "components": [
                {"name": "Systolic"}  # Missing value_quantity and value_quantity_unit
            ],
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("components[0].value_quantity" in e for e in response_data["errors"])
            assert any("components[0].value_quantity_unit" in e for e in response_data["errors"])

    def test_create_observation_invalid_category_type(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when category is not a string or list."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "category": 123,  # Invalid type
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("category" in e for e in response_data["errors"])

    def test_create_observation_note_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_id doesn't exist."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "note_id": 99999,
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_note_class.objects.filter.return_value.exists.return_value = False

                result = handler.create_observation()

                assert len(result) == 1
                response_data = json.loads(result[0].content)
                assert result[0].status_code == HTTPStatus.BAD_REQUEST
                assert "Note not found" in response_data["errors"]

    def test_create_observation_parent_observation_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when is_member_of_id doesn't exist."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "is_member_of_id": "nonexistent-obs-uuid",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Observation") as mock_obs_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_obs_class.objects.filter.return_value.exists.return_value = False

                result = handler.create_observation()

                assert len(result) == 1
                response_data = json.loads(result[0].content)
                assert result[0].status_code == HTTPStatus.BAD_REQUEST
                assert "Parent observation not found" in response_data["errors"]

    def test_create_observation_with_note_uuid(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test creating observation with note_uuid instead of note_id."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "note_uuid": "note-uuid-456",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                with patch("custom_observation_management.protocols.my_protocol.ObservationEffect") as mock_effect_class:
                    mock_patient_class.objects.filter.return_value.exists.return_value = True
                    # Return dbid when looking up note by UUID
                    mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                        "dbid": 12345
                    }
                    mock_effect_instance = MagicMock()
                    mock_effect_class.return_value = mock_effect_instance

                    result = handler.create_observation()

                    call_kwargs = mock_effect_class.call_args.kwargs
                    # Verify note_id was converted from note_uuid
                    assert call_kwargs["note_id"] == 12345
                    assert len(result) == 2
                    assert result[1].status_code == HTTPStatus.CREATED

    def test_create_observation_with_both_note_id_and_note_uuid(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when both note_id and note_uuid are provided."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "note_id": 12345,
            "note_uuid": "note-uuid-456",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("Cannot specify both" in e for e in response_data["errors"])

    def test_create_observation_note_uuid_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_uuid doesn't exist."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "note_uuid": "nonexistent-note-uuid",
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.my_protocol.Note") as mock_note_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = None

                result = handler.create_observation()

                assert len(result) == 1
                response_data = json.loads(result[0].content)
                assert result[0].status_code == HTTPStatus.BAD_REQUEST
                assert "Note not found" in response_data["errors"]

    def test_create_observation_note_uuid_invalid_type(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_uuid is not a string."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "note_uuid": 12345,  # Invalid type - should be string
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.my_protocol.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("'note_uuid' must be a string" in e for e in response_data["errors"])
