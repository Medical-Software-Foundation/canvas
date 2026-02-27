from http import HTTPStatus
from unittest.mock import MagicMock, patch, call
import json
import uuid
import pytest
from canvas_sdk.test_utils.factories import (
    NoteFactory,
    PatientFactory,
    PracticeLocationFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.note import NoteType
from note_command_api.protocols.note_api import NoteCommandAPI, CreateNoteAPI


class TestCreateNoteAPI:
    """Test suite for CreateNoteAPI SimpleAPI handler."""

    def test_create_note_success(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test successful POST request creates note and returns 202."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 2
            json_response = responses[1]
            assert json_response.status_code == HTTPStatus.ACCEPTED
            response_data = json.loads(json_response.content)
            assert response_data["message"] == "Note creation accepted"
            assert "note_id" in response_data

    def test_create_note_with_instance_id(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test successful POST request with provided instance_id."""
        instance_id = str(uuid.uuid4())
        request_body = {
            "instance_id": instance_id,
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 2
            json_response = responses[1]
            assert json_response.status_code == HTTPStatus.ACCEPTED
            response_data = json.loads(json_response.content)
            assert response_data["note_id"] == instance_id

    def test_create_note_with_title(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test successful POST request with optional title."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
            "title": "My Custom Note Title",
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            mock_note_effect_class.assert_called_once()
            call_kwargs = mock_note_effect_class.call_args[1]
            assert call_kwargs["title"] == "My Custom Note Title"

    def test_create_note_without_title(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test that omitting title from payload results in empty string on note effect."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            mock_note_effect_class.assert_called_once()
            call_kwargs = mock_note_effect_class.call_args[1]
            assert call_kwargs["title"] == ""

    def test_create_note_with_note_type_name(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test successful POST request using note_type_name instead of note_type_id."""
        request_body = {
            "note_type_name": note_type.name,
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 2
            assert responses[1].status_code == HTTPStatus.ACCEPTED

    def test_create_note_with_provider_name(self, mock_event, mock_request, note_type, patient, practice_location):
        """Test successful POST request using provider_name instead of provider_id."""
        staff = StaffFactory.create(first_name="John", last_name="Smith")
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_name": "John Smith",
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 2
            assert responses[1].status_code == HTTPStatus.ACCEPTED

    def test_create_note_with_practice_location_name(self, mock_event, mock_request, note_type, patient, staff):
        """Test successful POST request using practice_location_name instead of practice_location_id."""
        location = PracticeLocationFactory.create(full_name="Main Clinic")
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_name": "Main Clinic",
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 2
            assert responses[1].status_code == HTTPStatus.ACCEPTED

    def test_create_note_missing_note_type(self, mock_event, mock_request):
        """Test POST request missing note type identifier returns 400."""
        mock_request.json.return_value = {
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": "22345678-1234-1234-1234-123456789abc",
            "practice_location_id": "32345678-1234-1234-1234-123456789abc",
            "provider_id": "42345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("note_type_id" in err for err in response_data["errors"])

    def test_create_note_missing_datetime_of_service(self, mock_event, mock_request):
        """Test POST request missing datetime_of_service returns 400."""
        mock_request.json.return_value = {
            "note_type_id": "12345678-1234-1234-1234-123456789abc",
            "patient_id": "22345678-1234-1234-1234-123456789abc",
            "practice_location_id": "32345678-1234-1234-1234-123456789abc",
            "provider_id": "42345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("datetime_of_service" in err for err in response_data["errors"])

    def test_create_note_missing_patient_id(self, mock_event, mock_request):
        """Test POST request missing patient_id returns 400."""
        mock_request.json.return_value = {
            "note_type_id": "12345678-1234-1234-1234-123456789abc",
            "datetime_of_service": "2025-02-21 23:31:42",
            "practice_location_id": "32345678-1234-1234-1234-123456789abc",
            "provider_id": "42345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("patient_id" in err for err in response_data["errors"])

    def test_create_note_missing_practice_location(self, mock_event, mock_request):
        """Test POST request missing practice location identifier returns 400."""
        mock_request.json.return_value = {
            "note_type_id": "12345678-1234-1234-1234-123456789abc",
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": "22345678-1234-1234-1234-123456789abc",
            "provider_id": "42345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("practice_location" in err for err in response_data["errors"])

    def test_create_note_missing_provider(self, mock_event, mock_request):
        """Test POST request missing provider identifier returns 400."""
        mock_request.json.return_value = {
            "note_type_id": "12345678-1234-1234-1234-123456789abc",
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": "22345678-1234-1234-1234-123456789abc",
            "practice_location_id": "32345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("provider" in err for err in response_data["errors"])

    def test_create_note_invalid_uuid(self, mock_event, mock_request):
        """Test POST request with invalid UUID returns 400."""
        mock_request.json.return_value = {
            "instance_id": "not-a-valid-uuid",
            "note_type_id": "12345678-1234-1234-1234-123456789abc",
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": "22345678-1234-1234-1234-123456789abc",
            "practice_location_id": "32345678-1234-1234-1234-123456789abc",
            "provider_id": "42345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("Invalid instance_id" in err for err in response_data["errors"])

    def test_create_note_invalid_patient_id_uuid(self, mock_event, mock_request):
        """Test POST request with invalid patient_id UUID returns 400."""
        mock_request.json.return_value = {
            "note_type_id": "12345678-1234-1234-1234-123456789abc",
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": "invalid-patient-uuid",
            "practice_location_id": "32345678-1234-1234-1234-123456789abc",
            "provider_id": "42345678-1234-1234-1234-123456789abc",
        }

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("Invalid patient_id" in err for err in response_data["errors"])

    def test_create_note_duplicate_instance_id(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test POST request with existing instance_id returns 400."""
        existing_note = NoteFactory.create()
        request_body = {
            "instance_id": str(existing_note.id),
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert "Note already exists" in response_data["errors"]

    def test_create_note_note_type_not_found(self, mock_event, mock_request, patient, practice_location, staff):
        """Test POST request with non-existent note_type_id returns 400."""
        request_body = {
            "note_type_id": str(uuid.uuid4()),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert "Note type not found" in response_data["errors"]

    def test_create_note_patient_not_found(self, mock_event, mock_request, note_type, practice_location, staff):
        """Test POST request with non-existent patient_id returns 400."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(uuid.uuid4()),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert "Patient not found" in response_data["errors"]

    def test_create_note_practice_location_not_found(self, mock_event, mock_request, note_type, patient, staff):
        """Test POST request with non-existent practice_location_id returns 400."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(uuid.uuid4()),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert "Practice location not found" in response_data["errors"]

    def test_create_note_provider_not_found(self, mock_event, mock_request, note_type, patient, practice_location):
        """Test POST request with non-existent provider_id returns 400."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(uuid.uuid4()),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert "Provider not found" in response_data["errors"]

    def test_create_note_multiple_validation_errors(self, mock_event, mock_request):
        """Test POST request accumulates multiple validation errors."""
        request_body = {
            "note_type_id": str(uuid.uuid4()),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(uuid.uuid4()),
            "practice_location_id": str(uuid.uuid4()),
            "provider_id": str(uuid.uuid4()),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert len(response_data["errors"]) >= 4
        assert "Note type not found" in response_data["errors"]
        assert "Patient not found" in response_data["errors"]
        assert "Practice location not found" in response_data["errors"]
        assert "Provider not found" in response_data["errors"]

    def test_create_note_with_note_type_code(self, mock_event, mock_request, patient, practice_location, staff):
        """Test successful POST request using note_type_code instead of note_type_id."""
        note_type = NoteType.objects.create(
            name="Progress Note",
            display="Progress Note",
            code="progress-note",
            system="canvas",
            icon="note",
            category="encounter",
            rank=1,
            is_active=True,
            is_default_appointment_type=False,
            is_scheduleable=False,
            is_telehealth=False,
            is_billable=False,
            defer_place_of_service_to_practice_location=False,
            default_place_of_service="11",
            is_system_managed=False,
            is_visible=True,
            is_patient_required=True,
            allow_custom_title=False,
            is_scheduleable_via_patient_portal=False,
            unique_identifier="00000000-0000-0000-0000-000000000002",
            deprecated_at="2099-01-01 00:00:00",
            online_duration=0,
            available_places_of_service=["11"],
        )
        request_body = {
            "note_type_code": "progress-note",
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        with patch("note_command_api.protocols.note_api.NoteEffect") as mock_note_effect_class:
            mock_note_effect_class.return_value.create.return_value = MagicMock()

            handler = CreateNoteAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 2
            assert responses[1].status_code == HTTPStatus.ACCEPTED

    def test_create_note_invalid_datetime_format(self, mock_event, mock_request, note_type, patient, practice_location, staff):
        """Test POST request with invalid datetime_of_service format returns 400."""
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "not-a-valid-datetime",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_id": str(staff.id),
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert any("Invalid datetime_of_service" in err for err in response_data["errors"])

    def test_create_note_provider_name_no_match(self, mock_event, mock_request, note_type, patient, practice_location):
        """Test POST request with provider_name that doesn't match any provider returns 400."""
        StaffFactory.create(first_name="John", last_name="Smith")
        StaffFactory.create(first_name="Jane", last_name="Doe")
        request_body = {
            "note_type_id": str(note_type.id),
            "datetime_of_service": "2025-02-21 23:31:42",
            "patient_id": str(patient.id),
            "practice_location_id": str(practice_location.id),
            "provider_name": "Nonexistent Provider",
        }
        mock_request.json.return_value = request_body

        handler = CreateNoteAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert "Provider not found" in response_data["errors"]


class TestCreateNoteAPIHelperMethods:
    """Test suite for CreateNoteAPI helper methods directly."""

    def test_get_practice_location_identifier_no_identifier(self, mock_event):
        """Test get_practice_location_identifier returns None when no identifier provided."""
        handler = CreateNoteAPI(event=mock_event)
        result = handler.get_practice_location_identifier({})
        assert result is None

    def test_get_provider_identifier_no_identifier(self, mock_event):
        """Test get_provider_identifier returns None when no identifier provided."""
        handler = CreateNoteAPI(event=mock_event)
        result = handler.get_provider_identifier({})
        assert result is None

    def test_get_note_type_identifier_no_identifier(self, mock_event):
        """Test get_note_type_identifier returns None when no identifier provided."""
        handler = CreateNoteAPI(event=mock_event)
        result = handler.get_note_type_identifier({})
        assert result is None


class TestNoteCommandAPI:
    """Test suite for NoteCommandAPI SimpleAPI handler."""
    def test_get_note_success(self, mock_event, mock_request, mock_note, mock_command):
        """Test successful GET request returns note with enhanced command data."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            with patch("note_command_api.protocols.note_api.Command") as mock_command_class:
                mock_note_class.objects.get.return_value = mock_note
                mock_command_class.objects.get.return_value = mock_command
                handler = NoteCommandAPI(event=mock_event)
                handler.request = mock_request
                responses = handler.get()
                assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
                assert mock_command_class.objects.get.call_args == call(id="cmd-uuid-abc")
                assert mock_request.path_params.get.call_args == call("note_id")
                assert len(responses) == 1
                response = responses[0]
                assert response.status_code == HTTPStatus.OK
                response_data = json.loads(response.content)
                assert response_data["id"] == "test-note-uuid-123"
                assert response_data["dbid"] == 456
                assert response_data["title"] == "Test Note"
                assert response_data["current_state"] == "LKD"
                assert len(response_data["state_history"]) == 2
                assert response_data["state_history"][0]["state"] == "NEW"
                assert response_data["state_history"][0]["originator"]["id"] == "staff-uuid-1"
                assert response_data["state_history"][0]["originator"]["first_name"] == "John"
                assert response_data["state_history"][0]["originator"]["last_name"] == "Doe"
                assert response_data["state_history"][0]["originator"]["is_staff"] is True
                assert response_data["state_history"][1]["state"] == "LKD"
                assert response_data["patient"]["id"] == "patient-uuid-789"
                assert response_data["patient"]["first_name"] == "Alice"
                assert response_data["patient"]["last_name"] == "Johnson"
                assert response_data["patient"]["birth_date"] == "1980-05-15"
                assert response_data["originator"]["id"] == "originator-uuid"
                assert response_data["originator"]["first_name"] == "John"
                assert response_data["originator"]["last_name"] == "Doe"
                assert response_data["originator"]["is_staff"] is True
                assert response_data["provider"]["id"] == "provider-uuid"
                assert response_data["provider"]["first_name"] == "Jane"
                assert response_data["provider"]["last_name"] == "Smith"
                assert len(response_data["body"]) == 2
                command_item = response_data["body"][0]
                assert command_item["type"] == "command"
                assert "attributes" in command_item["data"]
                assert command_item["data"]["attributes"]["schema_key"] == "prescribe"
                assert command_item["data"]["attributes"]["data"]["medication"] == "Metformin 500mg"
                assert command_item["data"]["attributes"]["originator"]["id"] == "cmd-originator-uuid"
                assert command_item["data"]["attributes"]["originator"]["first_name"] == "Bob"
                assert command_item["data"]["attributes"]["originator"]["is_staff"] is True
                assert command_item["data"]["attributes"]["committer"]["id"] == "cmd-committer-uuid"
                assert command_item["data"]["attributes"]["committer"]["first_name"] == "Carol"
                assert command_item["data"]["attributes"]["committer"]["is_staff"] is True
                assert command_item["data"]["attributes"]["origination_source"] == "manual"
                assert command_item["data"]["attributes"]["entered_in_error_by"] is None
    def test_get_note_not_found(self, mock_event, mock_request):
        """Test GET request with non-existent note ID returns 404."""
        mock_request.path_params.get.return_value = "non-existent-uuid"
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            mock_note_class.DoesNotExist = Exception
            mock_note_class.objects.get.side_effect = mock_note_class.DoesNotExist()
            handler = NoteCommandAPI(event=mock_event)
            handler.request = mock_request
            responses = handler.get()
            assert mock_note_class.objects.get.call_args == call(id="non-existent-uuid")
            assert mock_request.path_params.get.call_args == call("note_id")
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.NOT_FOUND
            response_data = json.loads(response.content)
            assert response_data["error"] == "Note not found"
            assert response_data["note_id"] == "non-existent-uuid"
    def test_get_note_missing_note_id(self, mock_event, mock_request):
        """Test GET request without note_id returns 400."""
        mock_request.path_params.get.return_value = None
        handler = NoteCommandAPI(event=mock_event)
        handler.request = mock_request
        responses = handler.get()
        assert mock_request.path_params.get.call_args == call("note_id")
        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert response_data["error"] == "Note ID is required"
    def test_enhance_body_with_text_only(self, mock_event, mock_request, mock_note):
        """Test body enhancement when body contains only text entries and filters empty text."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_note.body = [
            {"type": "text", "value": "Line 1"},
            {"type": "text", "value": "Line 2"},
            {"type": "text", "value": ""},
        ]
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            mock_note_class.objects.get.return_value = mock_note
            handler = NoteCommandAPI(event=mock_event)
            handler.request = mock_request
            responses = handler.get()
            assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
            assert mock_request.path_params.get.call_args == call("note_id")
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK
            response_data = json.loads(response.content)
            assert len(response_data["body"]) == 2
            for item in response_data["body"]:
                assert item["type"] == "text"
                assert item["value"] != ""
                assert "attributes" not in item.get("data", {})
    def test_enhance_body_command_not_found(self, mock_event, mock_request, mock_note):
        """Test body enhancement when command lookup fails."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            with patch("note_command_api.protocols.note_api.Command") as mock_command_class:
                with patch("note_command_api.protocols.note_api.log") as mock_log:
                    mock_note_class.objects.get.return_value = mock_note
                    mock_command_class.DoesNotExist = Exception
                    mock_command_class.objects.get.side_effect = mock_command_class.DoesNotExist()
                    handler = NoteCommandAPI(event=mock_event)
                    handler.request = mock_request
                    responses = handler.get()
                    assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
                    assert mock_command_class.objects.get.call_args == call(id="cmd-uuid-abc")
                    assert mock_request.path_params.get.call_args == call("note_id")
                    assert mock_log.warning.call_args == call("Command not found: cmd-uuid-abc")
                    assert len(responses) == 1
                    response = responses[0]
                    assert response.status_code == HTTPStatus.OK
                    response_data = json.loads(response.content)
                    command_item = response_data["body"][0]
                    assert command_item["type"] == "command"
                    assert "attributes" not in command_item["data"]
    def test_enhance_body_command_missing_uuid(self, mock_event, mock_request, mock_note):
        """Test body enhancement when command entry has no command_uuid."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_note.body = [
            {"type": "text", "value": ""},
            {
                "type": "command",
                "value": "prescribe",
                "data": {
                    "id": 123
                }
            },
        ]
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            mock_note_class.objects.get.return_value = mock_note
            handler = NoteCommandAPI(event=mock_event)
            handler.request = mock_request
            responses = handler.get()
            assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
            assert mock_request.path_params.get.call_args == call("note_id")
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK
            response_data = json.loads(response.content)
            assert len(response_data["body"]) == 1
            command_item = response_data["body"][0]
            assert command_item["type"] == "command"
            assert "attributes" not in command_item["data"]
    def test_enhance_body_empty(self, mock_event, mock_request, mock_note):
        """Test body enhancement when body is empty."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_note.body = []
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            mock_note_class.objects.get.return_value = mock_note
            handler = NoteCommandAPI(event=mock_event)
            handler.request = mock_request
            responses = handler.get()
            assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
            assert mock_request.path_params.get.call_args == call("note_id")
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK
            response_data = json.loads(response.content)
            assert response_data["body"] == []
    def test_serialize_note_with_none_values(self, mock_event, mock_request, mock_note):
        """Test note serialization handles None values correctly."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_note.created = None
        mock_note.modified = None
        mock_note.patient = None
        mock_note.note_type_version = None
        mock_note.originator = None
        mock_note.provider = None
        mock_note.datetime_of_service = None
        mock_note.encounter = None
        mock_note.body = []
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            mock_note_class.objects.get.return_value = mock_note
            handler = NoteCommandAPI(event=mock_event)
            handler.request = mock_request
            responses = handler.get()
            assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
            assert mock_request.path_params.get.call_args == call("note_id")
            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.OK
            response_data = json.loads(response.content)
            assert response_data["created"] is None
            assert response_data["modified"] is None
            assert response_data["patient"] is None
            assert response_data["note_type_version"] is None
            assert response_data["originator"] is None
            assert response_data["provider"] is None
            assert response_data["datetime_of_service"] is None
            assert response_data["encounter"] is None
    def test_command_attributes_extraction(self, mock_event, mock_request, mock_note, mock_command):
        """Test command attributes are correctly extracted from command data."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            with patch("note_command_api.protocols.note_api.Command") as mock_command_class:
                mock_note_class.objects.get.return_value = mock_note
                mock_command_class.objects.get.return_value = mock_command
                handler = NoteCommandAPI(event=mock_event)
                handler.request = mock_request
                responses = handler.get()
                assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
                assert mock_command_class.objects.get.call_args == call(id="cmd-uuid-abc")
                assert mock_request.path_params.get.call_args == call("note_id")
                response = responses[0]
                response_data = json.loads(response.content)
                command_item = response_data["body"][0]
                attributes = command_item["data"]["attributes"]
                assert attributes["schema_key"] == "prescribe"
                assert attributes["state"] == "committed"
                assert "created" in attributes
                assert "modified" in attributes
                assert attributes["originator"]["id"] == "cmd-originator-uuid"
                assert attributes["originator"]["first_name"] == "Bob"
                assert attributes["originator"]["last_name"] == "Wilson"
                assert attributes["originator"]["is_staff"] is True
                assert attributes["committer"]["id"] == "cmd-committer-uuid"
                assert attributes["committer"]["first_name"] == "Carol"
                assert attributes["committer"]["last_name"] == "Brown"
                assert attributes["committer"]["is_staff"] is True
                assert attributes["entered_in_error_by"] is None
                assert attributes["origination_source"] == "manual"
                assert attributes["data"]["medication"] == "Metformin 500mg"
                assert attributes["data"]["sig"] == "Take 1 tablet twice daily"
                assert attributes["data"]["quantity"] == 60
                assert attributes["data"]["refills"] == 3
    def test_command_without_data_field(self, mock_event, mock_request, mock_note, mock_command):
        """Test command attributes extraction when command.data is None."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_command.data = None
        with patch("note_command_api.protocols.note_api.Note") as mock_note_class:
            with patch("note_command_api.protocols.note_api.Command") as mock_command_class:
                mock_note_class.objects.get.return_value = mock_note
                mock_command_class.objects.get.return_value = mock_command
                handler = NoteCommandAPI(event=mock_event)
                handler.request = mock_request
                responses = handler.get()
                assert mock_note_class.objects.get.call_args == call(id="test-note-uuid-123")
                assert mock_command_class.objects.get.call_args == call(id="cmd-uuid-abc")
                assert mock_request.path_params.get.call_args == call("note_id")
                response = responses[0]
                response_data = json.loads(response.content)
                command_item = response_data["body"][0]
                attributes = command_item["data"]["attributes"]
                assert attributes["schema_key"] == "prescribe"
                assert attributes["state"] == "committed"
                assert attributes["originator"]["id"] == "cmd-originator-uuid"
                assert attributes["originator"]["is_staff"] is True
                assert attributes["committer"]["id"] == "cmd-committer-uuid"
                assert attributes["committer"]["is_staff"] is True
                assert attributes["entered_in_error_by"] is None
                assert attributes["origination_source"] == "manual"
                assert "data" not in attributes
