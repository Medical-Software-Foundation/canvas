"""Tests for the CCM Activity Tracker API handler."""
import pytest
from datetime import datetime
from http import HTTPStatus
from unittest.mock import MagicMock, patch
from uuid import uuid4

from chronic_care_management_activity_tracker.handlers.ccmat_api import CcmatApi


class TestCcmatApi:
    """Test cases for the CcmatApi handler."""

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.render_to_string")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Staff")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.HTMLResponse")
    def test_index_returns_html_response(self, mock_html_response, mock_patient, mock_staff, mock_render):
        """Test that index returns an HTML response."""
        # Arrange
        mock_staff_obj = MagicMock()
        mock_staff_obj.full_name = "Dr. Test"
        mock_staff.objects.get.return_value = mock_staff_obj

        mock_patient_obj = MagicMock()
        mock_patient_obj.preferred_full_name = "Test Patient"
        mock_patient.objects.get.return_value = mock_patient_obj

        mock_render.return_value = "<html>test</html>"

        # Mock HTMLResponse to return itself
        mock_response_instance = MagicMock()
        mock_html_response.return_value = mock_response_instance

        api = CcmatApi()
        api.request = MagicMock()
        api.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        api.request.path_params = {"patient_id": "patient-123"}

        # Act
        # Call the unwrapped method directly (bypassing the decorator in tests)
        responses = api.index()

        # Assert
        assert len(responses) == 1
        assert responses[0] == mock_response_instance
        mock_render.assert_called_once()
        mock_staff.objects.get.assert_called_once_with(id="staff-123")
        mock_patient.objects.get.assert_called_once_with(id="patient-123")

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Response")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.render_to_string")
    def test_get_css_returns_css_response(self, mock_render, mock_response):
        """Test that get_css returns CSS response."""
        # Arrange
        mock_render.return_value = "body { color: red; }"
        mock_response_instance = MagicMock()
        mock_response.return_value = mock_response_instance

        api = CcmatApi()
        api.request = MagicMock()
        api.request.path_params = {"patient_id": "patient-123"}

        # Act
        responses = api.get_css()

        # Assert
        assert len(responses) == 1
        assert responses[0] == mock_response_instance
        mock_render.assert_called_once_with("static/css/styles.css")

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Response")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.render_to_string")
    def test_get_scripts_returns_js_response(self, mock_render, mock_response):
        """Test that get_scripts returns JavaScript response."""
        # Arrange
        mock_render.return_value = "console.log('test');"
        mock_response_instance = MagicMock()
        mock_response.return_value = mock_response_instance

        api = CcmatApi()
        api.request = MagicMock()
        api.request.path_params = {"patient_id": "patient-123"}

        # Act
        responses = api.get_scripts()

        # Assert
        assert len(responses) == 1
        assert responses[0] == mock_response_instance
        mock_render.assert_called_once()

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.JSONResponse")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.AddBannerAlert")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.QuestionnaireCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Questionnaire")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Appointment")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Staff")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Patient")
    def test_save_session_creates_note_and_effects(self, mock_patient, mock_staff, mock_appointment,
                                                     mock_note_type, mock_questionnaire, mock_questionnaire_cmd,
                                                     mock_note_effect, mock_banner, mock_json_response):
        """Test that save_session creates note, questionnaire, and banner."""
        # Arrange
        mock_staff_obj = MagicMock()
        mock_staff_obj.id = "staff-123"
        mock_staff_obj.full_name = "Dr. Test"
        mock_staff_obj.primary_practice_location.id = "location-123"
        mock_staff.objects.get.return_value = mock_staff_obj

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "patient-123"
        mock_patient_obj.preferred_full_name = "Test Patient"
        mock_patient_obj.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_patient.objects.get.return_value = mock_patient_obj

        mock_note_type.objects.get.return_value.id = "note-type-123"
        mock_appointment.objects.filter.return_value.values_list.return_value.order_by.return_value.first.return_value = None
        mock_questionnaire.objects.values_list.return_value.get.return_value = "questionnaire-123"

        # Mock QuestionnaireCommand
        mock_cmd_instance = MagicMock()
        mock_cmd_instance.questions = []
        mock_questionnaire_cmd.return_value = mock_cmd_instance

        # Mock effects and responses
        mock_json_response.return_value = MagicMock()
        mock_note_effect.return_value.create.return_value = MagicMock()
        mock_banner.return_value.apply.return_value = MagicMock()

        api = CcmatApi()
        api.request = MagicMock()
        api.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        api.request.path_params = {"patient_id": "patient-123"}
        api.request.json.return_value = {
            "activities": ["medication_review", "care_plan_update"],
            "timeLogs": [
                {"timestamp": "2024-01-01T10:00:00Z"},
                {"timestamp": "2024-01-01T10:30:00Z"}
            ],
            "notes": "Test notes"
        }

        # Act
        responses = api.save_session()

        # Assert
        assert len(responses) > 0
        # Verify key mocks were called
        mock_staff.objects.get.assert_called()
        mock_patient.objects.get.assert_called()
        mock_questionnaire_cmd.assert_called_once()
        mock_json_response.assert_called_once()
        mock_note_effect.assert_called_once()
        mock_banner.assert_called_once()

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.JSONResponse")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Staff")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Patient")
    def test_save_session_handles_patient_not_found(self, mock_patient, mock_staff, mock_json_response):
        """Test that save_session handles missing patient gracefully."""
        # Arrange
        # Create the DoesNotExist exception class
        class DoesNotExist(Exception):
            pass
        mock_patient.DoesNotExist = DoesNotExist

        mock_staff.objects.get.return_value = MagicMock(id="staff-123")
        mock_patient.objects.get.side_effect = DoesNotExist()

        # Mock the error JSON response
        error_response = MagicMock()
        mock_json_response.return_value = error_response

        api = CcmatApi()
        api.request = MagicMock()
        api.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        api.request.path_params = {"patient_id": "nonexistent"}
        api.request.json.return_value = {
            "activities": [],
            "timeLogs": [],
            "notes": ""
        }

        # Act
        responses = api.save_session()

        # Assert
        assert len(responses) == 1
        assert responses[0] == error_response
        # Should return error response with BAD_REQUEST status
        mock_json_response.assert_called_once()

    def test_get_this_month_seconds_with_no_interviews(self):
        """Test that _get_this_month_seconds returns 0 when no interviews exist."""
        # Arrange
        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

        api = CcmatApi()
        api.request = MagicMock()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        assert result == 0

    def test_get_this_month_seconds_with_valid_time(self):
        """Test that _get_this_month_seconds correctly parses time."""
        # Arrange
        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.values_list.return_value.first.return_value = "01:30:45"

        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_interview

        api = CcmatApi()
        api.request = MagicMock()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        # 1 hour + 30 minutes + 45 seconds = 5445 seconds
        assert result == 5445

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.JSONResponse")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.AddBannerAlert")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.QuestionnaireCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Questionnaire")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Appointment")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Staff")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Patient")
    def test_save_session_with_questionnaire_responses(self, mock_patient, mock_staff, mock_appointment,
                                                        mock_note_type, mock_questionnaire, mock_questionnaire_cmd,
                                                        mock_note_effect, mock_banner, mock_json_response):
        """Test that save_session populates questionnaire responses correctly."""
        # Arrange
        mock_staff_obj = MagicMock()
        mock_staff_obj.id = "staff-123"
        mock_staff_obj.full_name = "Dr. Test"
        mock_staff_obj.primary_practice_location.id = "location-123"
        mock_staff.objects.get.return_value = mock_staff_obj

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "patient-123"
        mock_patient_obj.preferred_full_name = "Test Patient"
        mock_patient_obj.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None
        mock_patient.objects.get.return_value = mock_patient_obj

        mock_note_type.objects.get.return_value.id = "note-type-123"
        mock_appointment.objects.filter.return_value.values_list.return_value.order_by.return_value.first.return_value = None
        mock_questionnaire.objects.values_list.return_value.get.return_value = "questionnaire-123"

        # Create mock questions with different codes
        mock_question_pt_name = MagicMock()
        mock_question_pt_name.coding.get.return_value = "ccm_session_pt_name_question"

        mock_question_staff_name = MagicMock()
        mock_question_staff_name.coding.get.return_value = "ccm_session_staff_name_question"

        mock_question_activities = MagicMock()
        mock_question_activities.coding.get.return_value = "ccm_session_activities_question"

        mock_question_notes = MagicMock()
        mock_question_notes.coding.get.return_value = "ccm_session_notes_question"

        mock_question_time_log = MagicMock()
        mock_question_time_log.coding.get.return_value = "ccm_session_time_log_question"

        mock_question_duration = MagicMock()
        mock_question_duration.coding.get.return_value = "ccm_session_duration_question"

        mock_question_month = MagicMock()
        mock_question_month.coding.get.return_value = "ccm_month_minutes_question"

        mock_cmd_instance = MagicMock()
        mock_cmd_instance.questions = [
            mock_question_pt_name,
            mock_question_staff_name,
            mock_question_activities,
            mock_question_notes,
            mock_question_time_log,
            mock_question_duration,
            mock_question_month,
        ]
        mock_questionnaire_cmd.return_value = mock_cmd_instance

        mock_json_response.return_value = MagicMock()
        mock_note_effect.return_value.create.return_value = MagicMock()
        mock_banner.return_value.apply.return_value = MagicMock()

        api = CcmatApi()
        api.request = MagicMock()
        api.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        api.request.path_params = {"patient_id": "patient-123"}
        api.request.json.return_value = {
            "activities": ["medication_review", "care_plan_update"],
            "timeLogs": [
                {"timestamp": "2024-01-01T10:00:00Z"},
                {"timestamp": "2024-01-01T10:30:00Z"}
            ],
            "notes": "Test session notes"
        }

        # Act
        responses = api.save_session()

        # Assert
        assert len(responses) > 0

        # Verify all questionnaire responses were populated
        mock_question_pt_name.add_response.assert_called_once_with(text="Test Patient")
        mock_question_staff_name.add_response.assert_called_once_with(text="Dr. Test")
        mock_question_activities.add_response.assert_called_once()
        mock_question_notes.add_response.assert_called_once_with(text="Test session notes")
        mock_question_time_log.add_response.assert_called_once()
        mock_question_duration.add_response.assert_called_once()
        mock_question_month.add_response.assert_called_once()

    def test_get_this_month_seconds_handles_invalid_format(self):
        """Test that _get_this_month_seconds returns 0 for invalid time format."""
        # Arrange
        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.values_list.return_value.first.return_value = "invalid-time"

        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_interview

        api = CcmatApi()
        api.request = MagicMock()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        assert result == 0  # Should return 0 for invalid format

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Note")
    def test_get_last_visit_place_of_service_returns_location(self, mock_note):
        """Test _get_last_visit_place_of_service returns most recent encounter location."""
        # Arrange
        mock_note.objects.values_list.return_value.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = "location-123"

        mock_patient = MagicMock()

        api = CcmatApi()

        # Act
        result = api._get_last_visit_place_of_service(mock_patient)

        # Assert
        assert result == "location-123"
        mock_note.objects.values_list.assert_called_once_with("place_of_service", flat=True)

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Note")
    def test_get_last_visit_place_of_service_returns_none_when_no_visits(self, mock_note):
        """Test _get_last_visit_place_of_service returns None when no visits found."""
        # Arrange
        mock_note.objects.values_list.return_value.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        mock_patient = MagicMock()

        api = CcmatApi()

        # Act
        result = api._get_last_visit_place_of_service(mock_patient)

        # Assert
        assert result is None

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Note")
    def test_get_patient_most_recent_practice_location_uses_last_visit(self, mock_note):
        """Test _get_patient_most_recent_practice_location prefers last visit location."""
        # Arrange
        mock_note.objects.values_list.return_value.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = "visit-location-456"

        mock_patient = MagicMock()
        mock_staff = MagicMock()
        mock_staff.primary_practice_location.id = "default-location-789"

        api = CcmatApi()

        # Act
        result = api._get_patient_most_recent_practice_location(mock_patient, mock_staff)

        # Assert
        assert result == "visit-location-456"

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Note")
    def test_get_patient_most_recent_practice_location_falls_back_to_staff_location(self, mock_note):
        """Test _get_patient_most_recent_practice_location falls back to staff location."""
        # Arrange
        mock_note.objects.values_list.return_value.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        mock_patient = MagicMock()
        mock_staff = MagicMock()
        mock_staff.primary_practice_location.id = "default-location-789"

        api = CcmatApi()

        # Act
        result = api._get_patient_most_recent_practice_location(mock_patient, mock_staff)

        # Assert
        assert result == "default-location-789"

    def test_get_this_month_seconds_with_empty_response(self):
        """Test _get_this_month_seconds returns 0 for empty string."""
        # Arrange
        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.values_list.return_value.first.return_value = ""

        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_interview

        api = CcmatApi()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        assert result == 0

    def test_get_this_month_seconds_with_whitespace(self):
        """Test _get_this_month_seconds returns 0 for whitespace."""
        # Arrange
        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.values_list.return_value.first.return_value = "   "

        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_interview

        api = CcmatApi()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        assert result == 0

    def test_get_this_month_seconds_with_malformed_time(self):
        """Test _get_this_month_seconds returns 0 for malformed time (wrong number of parts)."""
        # Arrange
        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.values_list.return_value.first.return_value = "12:34"  # Only 2 parts

        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_interview

        api = CcmatApi()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        assert result == 0

    def test_get_this_month_seconds_with_non_numeric_time(self):
        """Test _get_this_month_seconds returns 0 for non-numeric time values."""
        # Arrange
        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.values_list.return_value.first.return_value = "aa:bb:cc"

        mock_patient = MagicMock()
        mock_patient.interviews.filter.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_interview

        api = CcmatApi()

        with patch.object(api, "_get_questionnaire_id", return_value="test-q-id"):
            # Act
            result = api._get_this_month_seconds(mock_patient)

        # Assert
        assert result == 0

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.JSONResponse")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Staff")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_api.Patient")
    def test_save_session_handles_generic_exception(
            self, mock_patient, mock_staff, mock_note_type, mock_json_response
    ):
        """Test that save_session handles generic exceptions gracefully (covers lines 203-205)."""
        # Arrange
        mock_staff_obj = MagicMock()
        mock_staff_obj.id = "staff-123"
        mock_staff.objects.get.return_value = mock_staff_obj

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "patient-123"
        mock_patient.objects.get.return_value = mock_patient_obj

        # Create a DoesNotExist class that won't be caught by the first except block
        class DoesNotExist(Exception):
            pass
        mock_patient.DoesNotExist = DoesNotExist

        # Trigger a generic exception (not Patient.DoesNotExist) during note type lookup
        mock_note_type.objects.get.side_effect = RuntimeError("Unexpected database error")

        # Mock the error JSON response
        error_response = MagicMock()
        mock_json_response.return_value = error_response

        api = CcmatApi()
        api.request = MagicMock()
        api.request.headers = {"canvas-logged-in-user-id": "staff-123"}
        api.request.path_params = {"patient_id": "patient-123"}
        api.request.json.return_value = {
            "activities": ["medication_review"],
            "timeLogs": [
                {"timestamp": "2024-01-01T10:00:00Z"},
                {"timestamp": "2024-01-01T10:30:00Z"}
            ],
            "notes": "Test notes"
        }

        # Act
        responses = api.save_session()

        # Assert
        assert len(responses) == 1
        assert responses[0] == error_response
        # Verify it returned INTERNAL_SERVER_ERROR
        mock_json_response.assert_called_once()
        call_args = mock_json_response.call_args
        assert call_args[1]["status_code"] == HTTPStatus.INTERNAL_SERVER_ERROR
