from http import HTTPStatus
from unittest.mock import MagicMock, patch, call
import json
import pytest
from note_command_api.protocols.change_note_state import NoteStateChangeAPI


class TestNoteStateChangeAPI:
    """Test suite for NoteStateChangeAPI SimpleAPI handler."""

    def test_post_lock_note_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to lock a note."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_request.query_params.get.return_value = "lock"

        mock_appointment = MagicMock()
        mock_appointment.id = "appointment-uuid-123"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log") as mock_log:
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-123"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_lock_effect = MagicMock()
                        mock_effect_instance.lock.return_value = mock_lock_effect
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert mock_note_class.objects.filter.call_args == call(id="test-note-uuid-123")
                        assert mock_note_effect.call_args == call(instance_id="test-note-uuid-123")
                        assert mock_log.info.call_args == call(
                            "Attempting to lock note test-note-uuid-123 with appointment appointment-uuid-123"
                        )

                        assert len(responses) == 2
                        assert responses[0] == mock_lock_effect

                        json_response = responses[1]
                        assert json_response.status_code == HTTPStatus.OK
                        response_data = json.loads(json_response.content)
                        assert response_data["message"] == "Note test-note-uuid-123 state changed to lock"

    def test_post_unlock_note_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to unlock a note."""
        mock_request.path_params.get.return_value = "test-note-uuid-456"
        mock_request.query_params.get.return_value = "unlock"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log"):
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-456"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_unlock_effect = MagicMock()
                        mock_effect_instance.unlock.return_value = mock_unlock_effect
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert len(responses) == 2
                        assert responses[0] == mock_unlock_effect

                        json_response = responses[1]
                        assert json_response.status_code == HTTPStatus.OK
                        response_data = json.loads(json_response.content)
                        assert response_data["message"] == "Note test-note-uuid-456 state changed to unlock"

    def test_post_sign_note_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to sign a note."""
        mock_request.path_params.get.return_value = "test-note-uuid-789"
        mock_request.query_params.get.return_value = "sign"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log"):
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-789"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_sign_effect = MagicMock()
                        mock_effect_instance.sign.return_value = mock_sign_effect
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert len(responses) == 2
                        assert responses[0] == mock_sign_effect

                        json_response = responses[1]
                        assert json_response.status_code == HTTPStatus.OK
                        response_data = json.loads(json_response.content)
                        assert response_data["message"] == "Note test-note-uuid-789 state changed to sign"

    def test_post_push_charges_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to push charges for a note."""
        mock_request.path_params.get.return_value = "test-note-uuid-abc"
        mock_request.query_params.get.return_value = "push_charges"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log"):
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-abc"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_push_charges_effect = MagicMock()
                        mock_effect_instance.push_charges.return_value = mock_push_charges_effect
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert len(responses) == 2
                        assert responses[0] == mock_push_charges_effect

                        json_response = responses[1]
                        assert json_response.status_code == HTTPStatus.OK
                        response_data = json.loads(json_response.content)
                        assert response_data["message"] == "Note test-note-uuid-abc state changed to push_charges"

    def test_post_check_in_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to check in a note."""
        mock_request.path_params.get.return_value = "test-note-uuid-def"
        mock_request.query_params.get.return_value = "check_in"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log"):
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-def"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_check_in_effect = MagicMock()
                        mock_effect_instance.check_in.return_value = mock_check_in_effect
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert len(responses) == 2
                        assert responses[0] == mock_check_in_effect

                        json_response = responses[1]
                        assert json_response.status_code == HTTPStatus.OK
                        response_data = json.loads(json_response.content)
                        assert response_data["message"] == "Note test-note-uuid-def state changed to check_in"

    def test_post_no_show_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to mark note as no show."""
        mock_request.path_params.get.return_value = "test-note-uuid-ghi"
        mock_request.query_params.get.return_value = "no_show"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log"):
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-ghi"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_no_show_effect = MagicMock()
                        mock_effect_instance.no_show.return_value = mock_no_show_effect
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert len(responses) == 2
                        assert responses[0] == mock_no_show_effect

                        json_response = responses[1]
                        assert json_response.status_code == HTTPStatus.OK
                        response_data = json.loads(json_response.content)
                        assert response_data["message"] == "Note test-note-uuid-ghi state changed to no_show"

    def test_post_cancel_appointment_success(self, mock_event, mock_request, mock_note):
        """Test successful POST request to cancel appointment associated with note."""
        mock_request.path_params.get.return_value = "test-note-uuid-jkl"
        mock_request.query_params.get.return_value = "cancel"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.AppointmentEffect") as mock_appointment_effect:
                        with patch("note_command_api.protocols.change_note_state.log") as mock_log:
                            mock_note_filter = MagicMock()
                            mock_note_filter.first.return_value = mock_note
                            mock_note_class.objects.filter.return_value = mock_note_filter

                            mock_appointment_filter = MagicMock()
                            mock_appointment_values = MagicMock()
                            mock_appointment_values.last.return_value = "appointment-uuid-jkl"
                            mock_appointment_filter.values_list.return_value = mock_appointment_values
                            mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                            mock_note_effect_instance = MagicMock()
                            mock_note_effect.return_value = mock_note_effect_instance

                            mock_appt_effect_instance = MagicMock()
                            mock_cancel_effect = MagicMock()
                            mock_appt_effect_instance.cancel.return_value = mock_cancel_effect
                            mock_appointment_effect.return_value = mock_appt_effect_instance

                            handler = NoteStateChangeAPI(event=mock_event)
                            handler.request = mock_request

                            responses = handler.post()

                            assert mock_appointment_effect.call_args == call(instance_id="appointment-uuid-jkl")
                            assert mock_log.info.call_args == call(
                                "Attempting to cancel note test-note-uuid-jkl with appointment appointment-uuid-jkl"
                            )

                            assert len(responses) == 2
                            assert responses[0] == mock_cancel_effect

                            json_response = responses[1]
                            assert json_response.status_code == HTTPStatus.OK
                            response_data = json.loads(json_response.content)
                            assert response_data["message"] == "Note test-note-uuid-jkl state changed to cancel"

    def test_post_note_not_found(self, mock_event, mock_request):
        """Test POST request with non-existent note ID returns 404."""
        mock_request.path_params.get.return_value = "non-existent-uuid"
        mock_request.query_params.get.return_value = "lock"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            mock_note_filter = MagicMock()
            mock_note_filter.first.return_value = None
            mock_note_class.objects.filter.return_value = mock_note_filter

            handler = NoteStateChangeAPI(event=mock_event)
            handler.request = mock_request

            responses = handler.post()

            assert len(responses) == 1
            response = responses[0]
            assert response.status_code == HTTPStatus.NOT_FOUND
            response_data = json.loads(response.content)
            assert response_data["error"] == "Note not found"

    def test_post_missing_note_id(self, mock_event, mock_request):
        """Test POST request without note_id returns 400."""
        mock_request.path_params.get.return_value = None
        mock_request.query_params.get.return_value = "lock"

        handler = NoteStateChangeAPI(event=mock_event)
        handler.request = mock_request

        responses = handler.post()

        assert len(responses) == 1
        response = responses[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST
        response_data = json.loads(response.content)
        assert response_data["error"] == "Note ID is required"

    def test_post_missing_state_parameter(self, mock_event, mock_request, mock_note):
        """Test POST request without state query parameter returns 400."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_request.query_params.get.return_value = None

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                mock_note_filter = MagicMock()
                mock_note_filter.first.return_value = mock_note
                mock_note_class.objects.filter.return_value = mock_note_filter

                mock_appointment_filter = MagicMock()
                mock_appointment_values = MagicMock()
                mock_appointment_values.last.return_value = "appointment-uuid-123"
                mock_appointment_filter.values_list.return_value = mock_appointment_values
                mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                handler = NoteStateChangeAPI(event=mock_event)
                handler.request = mock_request

                responses = handler.post()

                assert len(responses) == 1
                response = responses[0]
                assert response.status_code == HTTPStatus.BAD_REQUEST
                response_data = json.loads(response.content)
                assert response_data["error"] == "Note state is required"

    def test_post_invalid_state(self, mock_event, mock_request, mock_note):
        """Test POST request with invalid state returns 400."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_request.query_params.get.return_value = "invalid_state"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.AppointmentEffect") as mock_appointment_effect:
                        with patch("note_command_api.protocols.change_note_state.log"):
                            mock_note_filter = MagicMock()
                            mock_note_filter.first.return_value = mock_note
                            mock_note_class.objects.filter.return_value = mock_note_filter

                            mock_appointment_filter = MagicMock()
                            mock_appointment_values = MagicMock()
                            mock_appointment_values.last.return_value = "appointment-uuid-123"
                            mock_appointment_filter.values_list.return_value = mock_appointment_values
                            mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                            mock_note_effect_instance = MagicMock()
                            mock_note_effect.return_value = mock_note_effect_instance

                            mock_appt_effect_instance = MagicMock()
                            mock_appointment_effect.return_value = mock_appt_effect_instance

                            handler = NoteStateChangeAPI(event=mock_event)
                            handler.request = mock_request

                            responses = handler.post()

                            assert len(responses) == 1
                            response = responses[0]
                            assert response.status_code == HTTPStatus.BAD_REQUEST
                            response_data = json.loads(response.content)
                            assert response_data["error"] == "Invalid note state"

    def test_post_effect_exception(self, mock_event, mock_request, mock_note):
        """Test POST request handles exceptions from effect execution."""
        mock_request.path_params.get.return_value = "test-note-uuid-123"
        mock_request.query_params.get.return_value = "lock"

        with patch("note_command_api.protocols.change_note_state.Note") as mock_note_class:
            with patch("note_command_api.protocols.change_note_state.Appointment") as mock_appointment_class:
                with patch("note_command_api.protocols.change_note_state.NoteEffect") as mock_note_effect:
                    with patch("note_command_api.protocols.change_note_state.log") as mock_log:
                        mock_note_filter = MagicMock()
                        mock_note_filter.first.return_value = mock_note
                        mock_note_class.objects.filter.return_value = mock_note_filter

                        mock_appointment_filter = MagicMock()
                        mock_appointment_values = MagicMock()
                        mock_appointment_values.last.return_value = "appointment-uuid-123"
                        mock_appointment_filter.values_list.return_value = mock_appointment_values
                        mock_appointment_class.objects.filter.return_value = mock_appointment_filter.order_by.return_value = mock_appointment_filter

                        mock_effect_instance = MagicMock()
                        mock_effect_instance.lock.side_effect = Exception("Test error")
                        mock_note_effect.return_value = mock_effect_instance

                        handler = NoteStateChangeAPI(event=mock_event)
                        handler.request = mock_request

                        responses = handler.post()

                        assert mock_log.error.call_args == call("Error changing note state: Test error")

                        assert len(responses) == 1
                        response = responses[0]
                        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
                        response_data = json.loads(response.content)
                        assert response_data["error"] == "Test error"
