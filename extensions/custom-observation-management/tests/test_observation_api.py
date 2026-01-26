"""Tests for the ObservationAPI SimpleAPI handler."""

import json
from datetime import datetime, timezone
from http import HTTPStatus
from unittest.mock import MagicMock, patch, call

import pytest

from custom_observation_management.protocols.observation_api import ObservationAPI


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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
                with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                    mock_patient_class.objects.filter.return_value.exists.return_value = True
                    mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
                    mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                        "id": "note-uuid-123",
                        "datetime_of_service": None,
                    }

                    result = handler.get_observations_for_patient()

                    mock_patient_class.objects.filter.assert_called_with(id="patient-uuid-123")
                    assert len(result) == 1
                    response_data = json.loads(result[0].content)
                    assert "observations" in response_data
                    assert "pagination" in response_data
                    assert isinstance(response_data["observations"], list)

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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
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

        with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
            with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
                mock_note_class.objects.filter.return_value.exists.return_value = True
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]

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

        with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]
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

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
                with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                with patch("custom_observation_management.protocols.observation_api.ObservationEffect") as mock_effect_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("'note_uuid' must be a string" in e for e in response_data["errors"])

    def test_create_observation_invalid_value_type(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when value is not a string."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "value": 120,  # Invalid type - should be string
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("'value' must be a string" in e for e in response_data["errors"])

    def test_create_observation_invalid_units_type(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when units is not a string."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "units": 123,  # Invalid type - should be string
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("'units' must be a string" in e for e in response_data["errors"])

    def test_create_observation_invalid_note_id_type(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_id is not an integer."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "note_id": "not-an-int",  # Invalid type - should be integer
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("'note_id' must be an integer" in e for e in response_data["errors"])

    def test_create_observation_invalid_is_member_of_id_type(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when is_member_of_id is not a string."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "is_member_of_id": 12345,  # Invalid type - should be string
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("'is_member_of_id' must be a string" in e for e in response_data["errors"])

    def test_create_observation_invalid_category_list_contents(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when category list contains non-strings."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "category": ["vital-signs", 123],  # Invalid - list contains non-string
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("category" in e for e in response_data["errors"])

    def test_create_observation_codings_not_object(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when codings contains non-object items."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "codings": ["not-an-object"],  # Invalid - should be dict
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("codings[0]' must be an object" in e for e in response_data["errors"])

    def test_create_observation_components_not_object(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when components contains non-object items."""
        mock_request.json.return_value = {
            "patient_id": "patient-uuid-123",
            "name": "Blood Pressure",
            "effective_datetime": "2024-06-15T10:30:00Z",
            "components": ["not-an-object"],  # Invalid - should be dict
        }

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = True

            result = handler.create_observation()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert any("components[0]' must be an object" in e for e in response_data["errors"])


class TestGetObservationsPagination:
    """Tests for pagination in GET /observations endpoint."""

    def test_pagination_page_less_than_one_returns_empty_results(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that page < 1 returns expected response (page value used as-is in response)."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"page": "0", "page_size": "10", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                # Page 0 internally gets normalized to page 1 for slicing
                # but current_page in response shows the original parsed value
                assert response_data["pagination"]["current_page"] == 0
                assert result[0].status_code == HTTPStatus.OK

    def test_pagination_page_exceeds_total_pages(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that page > total_pages returns expected response."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"page": "100", "page_size": "10", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                # With 1 observation and page_size 10, total_pages = 1
                # Page value in response matches original parsed value
                assert response_data["pagination"]["current_page"] == 100
                assert response_data["pagination"]["total_pages"] == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_pagination_invalid_page_defaults_to_one(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that invalid page value defaults to 1."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"page": "not-a-number", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                assert response_data["pagination"]["current_page"] == 1
                assert response_data["pagination"]["page_size"] == 25

    def test_pagination_page_size_capped_at_100(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that page_size is capped at 100."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"page_size": "500", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                assert response_data["pagination"]["page_size"] == 100


class TestGetObservationsSorting:
    """Tests for sorting in GET /observations endpoint."""

    def test_sort_by_name(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test sorting by name."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"sort_by": "name", "sort_order": "asc", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK

    def test_sort_by_value_numeric(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test sorting by numeric value."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"sort_by": "value", "sort_order": "asc", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        # Create observations with numeric values
        mock_obs1 = MagicMock()
        mock_obs1.id = "obs-1"
        mock_obs1.name = "Weight"
        mock_obs1.value = "150"
        mock_obs1.category = "vital-signs"
        mock_obs1.units = "lbs"
        mock_obs1.note_id = 123
        mock_obs1.effective_datetime = None
        mock_obs1.patient = MagicMock()
        mock_obs1.patient.id = "patient-uuid"
        mock_obs1.patient.first_name = "John"
        mock_obs1.patient.last_name = "Doe"
        mock_obs1.is_member_of = None
        mock_obs1.codings.all.return_value = []
        mock_obs1.components.all.return_value = []
        mock_obs1.value_codings.all.return_value = []

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_obs1]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK

    def test_sort_by_units(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test sorting by units."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"sort_by": "units", "sort_order": "desc", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK

    def test_sort_by_category(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test sorting by category."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"sort_by": "category", "sort_order": "asc", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK

    def test_invalid_sort_by_defaults_to_date(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that invalid sort_by defaults to 'date'."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"sort_by": "invalid_column", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK

    def test_invalid_sort_order_defaults_to_desc(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that invalid sort_order defaults to 'desc'."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"sort_order": "invalid_order", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK


class TestGetObservationsUngrouped:
    """Tests for ungrouped mode in GET /observations endpoint."""

    def test_ungrouped_mode_returns_flat_list(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that ungrouped=true returns flat list without grouping."""
        mock_request.query_params = {"ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                assert result[0].status_code == HTTPStatus.OK
                # Each observation should have empty members in ungrouped mode
                for obs in response_data["observations"]:
                    assert obs.get("members") == []

    def test_ungrouped_false_groups_observations(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test that ungrouped=false (default) groups observations."""
        mock_request.query_params = {"ungrouped": "false"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                # Setup for grouped mode - needs more complex mocking
                base_exclude = MagicMock()
                mock_obs_class.objects.exclude.return_value = base_exclude
                base_exclude.exclude.return_value.exclude.return_value.filter.return_value = MagicMock()

                # Mock the filter chain for grouped mode
                filter_result = MagicMock()
                base_exclude.exclude.return_value.exclude.return_value.filter.return_value = filter_result
                filter_result.exclude.return_value.values_list.return_value = []
                filter_result.filter.return_value.values_list.return_value = [mock_observation.id]
                base_exclude.exclude.return_value.exclude.return_value.filter.return_value.order_by.return_value = [mock_observation]

                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK


class TestGetObservationsNoteUuidFilter:
    """Tests for note_uuid filter in GET /observations endpoint."""

    def test_note_uuid_filter_success(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering by note_uuid."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"note_uuid": "note-uuid-456", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
            with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
                # First call is for note_uuid lookup, returns dbid
                # Subsequent calls are for _map_observation_to_dict which needs id and datetime_of_service
                mock_note_class.objects.filter.return_value.values.return_value.first.side_effect = [
                    {"dbid": 12345},  # First call: note_uuid filter lookup
                    {"id": "note-uuid-123", "datetime_of_service": None},  # Second call: observation mapping
                ]
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]

                result = handler.get_observations_for_patient()

                assert len(result) == 1
                assert result[0].status_code == HTTPStatus.OK

    def test_note_uuid_filter_not_found(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_uuid doesn't exist."""
        mock_request.query_params = {"note_uuid": "nonexistent-note-uuid"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
            mock_note_class.objects.filter.return_value.values.return_value.first.return_value = None

            result = handler.get_observations_for_patient()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.NOT_FOUND
            assert "Note not found" in response_data["error"]

    def test_note_uuid_filter_invalid_raises_error(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_uuid causes an exception."""
        mock_request.query_params = {"note_uuid": "invalid-uuid-format"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
            mock_note_class.objects.filter.return_value.values.return_value.first.side_effect = Exception("Invalid UUID")

            result = handler.get_observations_for_patient()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert "Invalid note_uuid" in response_data["error"]

    def test_note_dbid_filter_invalid_raises_error(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test error when note_dbid causes an exception."""
        mock_request.query_params = {"note_dbid": "invalid"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
            mock_note_class.objects.filter.return_value.exists.side_effect = Exception("Invalid format")

            result = handler.get_observations_for_patient()

            assert len(result) == 1
            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.BAD_REQUEST
            assert "Invalid note_dbid" in response_data["error"]


class TestGetObservationsNameFallback:
    """Tests for name fallback logic (using codings[0].display when name is blank)."""

    def test_name_fallback_to_codings_display(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test that blank name falls back to codings[0].display."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        # Create observation with blank name but valid codings
        mock_obs = MagicMock()
        mock_obs.id = "obs-uuid-123"
        mock_obs.name = ""  # Blank name
        mock_obs.category = "vital-signs"
        mock_obs.value = "120/80"
        mock_obs.units = "mmHg"
        mock_obs.note_id = 12345
        mock_obs.effective_datetime = None
        mock_obs.patient = MagicMock()
        mock_obs.patient.id = "patient-uuid-123"
        mock_obs.patient.first_name = "John"
        mock_obs.patient.last_name = "Doe"
        mock_obs.is_member_of = None
        mock_obs.components.all.return_value = []
        mock_obs.value_codings.all.return_value = []

        # Mock coding with display value
        mock_coding = MagicMock()
        mock_coding.system = "http://loinc.org"
        mock_coding.code = "85354-9"
        mock_coding.display = "Blood Pressure Panel"  # This should be used as fallback
        mock_coding.version = ""
        mock_coding.user_selected = False
        mock_obs.codings.all.return_value = [mock_coding]

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_obs]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                # The name should fall back to codings[0].display
                assert response_data["observations"][0]["name"] == "Blood Pressure Panel"


class TestGetObservationsValueFallback:
    """Tests for value fallback logic (using value_codings when value is blank)."""

    def test_value_fallback_to_value_codings(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test that blank value falls back to comma-separated value_codings displays."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        # Create observation with blank value but valid value_codings
        mock_obs = MagicMock()
        mock_obs.id = "obs-uuid-123"
        mock_obs.name = "Smoking Status"
        mock_obs.category = "social-history"
        mock_obs.value = ""  # Blank value
        mock_obs.units = None
        mock_obs.note_id = 12345
        mock_obs.effective_datetime = None
        mock_obs.patient = MagicMock()
        mock_obs.patient.id = "patient-uuid-123"
        mock_obs.patient.first_name = "John"
        mock_obs.patient.last_name = "Doe"
        mock_obs.is_member_of = None
        mock_obs.components.all.return_value = []
        mock_obs.codings.all.return_value = []

        # Mock value_codings with display values
        mock_value_coding = MagicMock()
        mock_value_coding.system = "http://snomed.info/sct"
        mock_value_coding.code = "266919005"
        mock_value_coding.display = "Never smoked"  # This should be used as fallback
        mock_value_coding.version = ""
        mock_value_coding.user_selected = False
        mock_obs.value_codings.all.return_value = [mock_value_coding]

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_obs]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                response_data = json.loads(result[0].content)
                # The value should fall back to value_codings[0].display
                assert response_data["observations"][0]["value"] == "Never smoked"


class TestGetObservationFilters:
    """Tests for GET /observation-filters endpoint."""

    def test_get_observation_filters_success(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test successfully getting observation filters."""
        mock_request.query_params = {}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        mock_obs = MagicMock()
        mock_obs.name = "Blood Pressure"
        mock_obs.codings.first.return_value = None

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            queryset_mock = MagicMock()
            mock_obs_class.objects.exclude.return_value = queryset_mock
            queryset_mock.prefetch_related.return_value = [mock_obs]
            queryset_mock.exclude.return_value.exclude.return_value.values_list.return_value.distinct.return_value.order_by.return_value = ["vital-signs"]

            result = handler.get_observation_filters()

            assert len(result) == 1
            assert result[0].status_code == HTTPStatus.OK

    def test_get_observation_filters_with_patient_id(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test getting observation filters filtered by patient_id."""
        mock_request.query_params = {"patient_id": "patient-uuid-123"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
                mock_patient_class.objects.filter.return_value.exists.return_value = True

                queryset_mock = MagicMock()
                mock_obs_class.objects.exclude.return_value = queryset_mock
                queryset_mock.filter.return_value = queryset_mock
                queryset_mock.prefetch_related.return_value = []
                queryset_mock.exclude.return_value.exclude.return_value.values_list.return_value.distinct.return_value.order_by.return_value = []

                result = handler.get_observation_filters()

                assert result[0].status_code == HTTPStatus.OK

    def test_get_observation_filters_patient_not_found(
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

        with patch("custom_observation_management.protocols.observation_api.Patient") as mock_patient_class:
            mock_patient_class.objects.filter.return_value.exists.return_value = False

            result = handler.get_observation_filters()

            response_data = json.loads(result[0].content)
            assert result[0].status_code == HTTPStatus.NOT_FOUND
            assert "Patient not found" in response_data["error"]

    def test_get_observation_filters_name_fallback_to_codings(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
    ) -> None:
        """Test that observation filters uses codings fallback for names."""
        mock_request.query_params = {}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        # Create observation with blank name but valid codings
        mock_obs = MagicMock()
        mock_obs.name = ""  # Blank name
        mock_coding = MagicMock()
        mock_coding.display = "Blood Pressure Panel"
        mock_obs.codings.first.return_value = mock_coding

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            queryset_mock = MagicMock()
            mock_obs_class.objects.exclude.return_value = queryset_mock
            queryset_mock.prefetch_related.return_value = [mock_obs]
            queryset_mock.exclude.return_value.exclude.return_value.values_list.return_value.distinct.return_value.order_by.return_value = []

            result = handler.get_observation_filters()

            response_data = json.loads(result[0].content)
            assert "Blood Pressure Panel" in response_data["names"]


class TestGetObservationsWithNameFilterAndPipeSeparator:
    """Tests for name filter using || separator."""

    def test_name_filter_with_pipe_separator(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering by multiple names using || separator."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"name": "Blood Pressure||Heart Rate", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK

    def test_category_filter_with_pipe_separator(
        self,
        mock_event: MagicMock,
        mock_request: MagicMock,
        mock_secrets: dict[str, str],
        mock_observation: MagicMock,
    ) -> None:
        """Test filtering by multiple categories using || separator."""
        # Use ungrouped mode for simpler mocking
        mock_request.query_params = {"category": "vital-signs||laboratory", "ungrouped": "true"}

        handler = ObservationAPI(event=mock_event)
        handler.request = mock_request
        handler.secrets = mock_secrets

        with patch("custom_observation_management.protocols.observation_api.Observation") as mock_obs_class:
            with patch("custom_observation_management.protocols.observation_api.Note") as mock_note_class:
                mock_obs_class.objects.exclude.return_value.exclude.return_value.exclude.return_value.filter.return_value = [mock_observation]
                mock_note_class.objects.filter.return_value.values.return_value.first.return_value = {
                    "id": "note-uuid-123",
                    "datetime_of_service": None,
                }

                result = handler.get_observations_for_patient()

                assert result[0].status_code == HTTPStatus.OK
