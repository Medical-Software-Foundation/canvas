from http import HTTPStatus
from unittest.mock import MagicMock, patch, call
import json
import pytest
from note_command_api.protocols.note_api import NoteCommandAPI
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
