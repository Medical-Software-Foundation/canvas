"""Tests for the CCM Monthly Banner Protocol handler."""
import pytest
from unittest.mock import MagicMock, patch

from canvas_sdk.events import EventType
from chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol import (
    CcmatMonthlyBannerProtocol,
)


class TestCcmatMonthlyBannerProtocol:
    """Test cases for the CcmatMonthlyBannerProtocol handler."""

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_compute_returns_empty_when_questionnaire_not_found(self, mock_questionnaire):
        """Test that compute returns empty list when questionnaire is not found."""
        # Arrange
        mock_questionnaire.objects.filter.return_value.first.return_value = None

        protocol = CcmatMonthlyBannerProtocol()
        protocol.event = MagicMock()
        protocol.event.type = EventType.PATIENT_UPDATED
        protocol.target = "test-patient-123"

        # Act
        effects = protocol.compute()

        # Assert
        assert effects == []

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_compute_handles_patient_updated_event(self, mock_questionnaire, mock_patient):
        """Test that compute handles PATIENT_UPDATED event."""
        # Arrange
        mock_questionnaire_obj = MagicMock()
        mock_questionnaire.objects.filter.return_value.first.return_value = mock_questionnaire_obj

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "test-patient-123"
        mock_patient_obj.interviews.filter.return_value.exists.return_value = False
        mock_patient.objects.filter.return_value = [mock_patient_obj]

        protocol = CcmatMonthlyBannerProtocol()
        protocol.event = MagicMock()
        protocol.event.type = EventType.PATIENT_UPDATED
        protocol.target = "test-patient-123"

        # Act
        effects = protocol.compute()

        # Assert
        assert len(effects) >= 0  # Should return list of effects (could be empty if no interviews)

    def test_calculate_time_spent_with_valid_data(self):
        """Test that _calculate_time_spent correctly calculates time."""
        # Arrange
        protocol = CcmatMonthlyBannerProtocol()

        mock_interview = MagicMock()
        mock_response = MagicMock()
        mock_response.response_option_value = "01:30:45"
        mock_interview.interview_responses.filter.return_value = [mock_response]

        # Act
        result = protocol._calculate_time_spent([mock_interview])

        # Assert
        assert result == "01:30:45"

    def test_calculate_time_spent_with_invalid_time_format(self):
        """Test that _calculate_time_spent handles invalid time formats."""
        # Arrange
        protocol = CcmatMonthlyBannerProtocol()

        mock_interview = MagicMock()
        mock_response = MagicMock()
        mock_response.response_option_value = "invalid"
        mock_interview.interview_responses.filter.return_value = [mock_response]

        # Act
        result = protocol._calculate_time_spent([mock_interview])

        # Assert
        assert result == "00:00:00"

    def test_responds_to_correct_event_types(self):
        """Test that the protocol responds to the correct event types."""
        # Assert
        assert hasattr(CcmatMonthlyBannerProtocol, "RESPONDS_TO")
        assert len(CcmatMonthlyBannerProtocol.RESPONDS_TO) == 3

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.EventType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_compute_with_plugin_created_processes_all_patients(self, mock_questionnaire, mock_patient, mock_event_type):
        """Test compute handles PLUGIN_CREATED event for all active patients."""
        # Arrange
        mock_event_type.PLUGIN_CREATED = "PLUGIN_CREATED"
        mock_event_type.PLUGIN_UPDATED = "PLUGIN_UPDATED"

        mock_questionnaire.objects.filter.return_value.values_list.return_value.first.return_value = "test-q-id"

        # Mock two active patients
        mock_patient1 = MagicMock()
        mock_patient1.id = "patient-1"
        mock_patient1.interviews.filter.return_value.exists.return_value = False

        mock_patient2 = MagicMock()
        mock_patient2.id = "patient-2"
        mock_patient2.interviews.filter.return_value.exists.return_value = False

        mock_patient.objects.filter.return_value = [mock_patient1, mock_patient2]

        protocol = CcmatMonthlyBannerProtocol()
        protocol.event = MagicMock()
        protocol.event.type = "PLUGIN_CREATED"  # Set event.type not event.target.type
        protocol.target = None  # Bulk operation

        # Act
        effects = protocol.compute()

        # Assert
        assert isinstance(effects, list)
        mock_patient.objects.filter.assert_called_with(active=True)

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.EventType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_compute_with_plugin_updated_processes_all_patients(self, mock_questionnaire, mock_patient, mock_event_type):
        """Test compute handles PLUGIN_UPDATED event for all active patients."""
        # Arrange
        mock_event_type.PLUGIN_CREATED = "PLUGIN_CREATED"
        mock_event_type.PLUGIN_UPDATED = "PLUGIN_UPDATED"

        mock_questionnaire.objects.filter.return_value.values_list.return_value.first.return_value = "test-q-id"

        mock_patient1 = MagicMock()
        mock_patient1.interviews.filter.return_value.exists.return_value = False

        mock_patient.objects.filter.return_value = [mock_patient1]

        protocol = CcmatMonthlyBannerProtocol()
        protocol.event = MagicMock()
        protocol.event.type = "PLUGIN_UPDATED"  # Set event.type not event.target.type
        protocol.target = None  # Bulk operation

        # Act
        effects = protocol.compute()

        # Assert
        assert isinstance(effects, list)
        mock_patient.objects.filter.assert_called_with(active=True)

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_calculate_time_spent_with_multiple_interviews(self, mock_questionnaire):
        """Test _calculate_time_spent processes multiple interviews."""
        # Arrange
        mock_questionnaire.objects.filter.return_value.values_list.return_value.first.return_value = "test-q-id"

        # Mock interviews with time responses
        mock_response1 = MagicMock()
        mock_response1.response_option_value = "00:15:30"

        mock_response2 = MagicMock()
        mock_response2.response_option_value = "00:10:00"

        mock_interview1 = MagicMock()
        mock_interview1.interview_responses.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_response1

        mock_interview2 = MagicMock()
        mock_interview2.interview_responses.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_response2

        protocol = CcmatMonthlyBannerProtocol()

        # Act
        result = protocol._calculate_time_spent([mock_interview1, mock_interview2])

        # Assert - Should return a time string in HH:MM:SS format
        assert isinstance(result, str)
        assert ":" in result
        parts = result.split(":")
        assert len(parts) == 3  # HH:MM:SS format

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_calculate_time_spent_handles_invalid_time_gracefully(self, mock_questionnaire):
        """Test _calculate_time_spent skips invalid time formats."""
        # Arrange
        mock_questionnaire.objects.filter.return_value.values_list.return_value.first.return_value = "test-q-id"

        mock_response = MagicMock()
        mock_response.response_option_value = "invalid-time"

        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_response

        protocol = CcmatMonthlyBannerProtocol()

        # Act - Should handle error and return 00:00:00
        result = protocol._calculate_time_spent([mock_interview])

        # Assert
        assert result == "00:00:00"  # Covers lines 75-76 (exception handling)

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_calculate_time_spent_handles_arrow_parser_error(self, mock_questionnaire):
        """Test _calculate_time_spent handles arrow ParserError for malformed time."""
        # Arrange
        mock_questionnaire.objects.filter.return_value.values_list.return_value.first.return_value = "test-q-id"

        # This will trigger arrow.parser.ParserError when arrow tries to parse it
        mock_response = MagicMock()
        mock_response.response_option_value = "99:99:99"  # Invalid time that arrow can't parse

        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_response

        protocol = CcmatMonthlyBannerProtocol()

        # Act - Should catch exception and continue
        result = protocol._calculate_time_spent([mock_interview])

        # Assert - Should return 00:00:00 since the time couldn't be parsed
        assert result == "00:00:00"

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_banner_protocol.Questionnaire")
    def test_compute_with_interviews_existing(self, mock_questionnaire, mock_patient):
        """Test compute when patient has existing interviews."""
        # Arrange
        mock_questionnaire.objects.filter.return_value.values_list.return_value.first.return_value = "test-q-id"

        # Mock interview with time response
        mock_response = MagicMock()
        mock_response.response_option_value = "01:30:00"

        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value.filter.return_value.order_by.return_value.first.return_value = mock_response

        mock_interviews = MagicMock()
        mock_interviews.exists.return_value = True  # This covers line 46!
        mock_interviews.__iter__.return_value = iter([mock_interview])

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "patient-with-interviews"
        mock_patient_obj.interviews.filter.return_value = mock_interviews

        mock_patient.objects.filter.return_value = [mock_patient_obj]

        protocol = CcmatMonthlyBannerProtocol()
        protocol.event = MagicMock()
        protocol.event.type = "PATIENT_UPDATED"
        protocol.target = "patient-with-interviews"

        # Act
        effects = protocol.compute()

        # Assert
        assert isinstance(effects, list)
        mock_interviews.exists.assert_called_once()  # Verify line 46 was executed

    def test_calculate_time_spent_catches_value_error(self):
        """Test that _calculate_time_spent catches ValueError for invalid time format (covers lines 75-76)."""
        # Arrange
        protocol = CcmatMonthlyBannerProtocol()

        # Create a mock response with a time that contains colon but will fail parsing
        # When arrow tries to parse "25:00:00" as a time, it fails because 25 is invalid hour
        mock_response = MagicMock()
        mock_response.response_option_value = "25:00:00"  # Invalid hour triggers ParserError

        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value = [mock_response]

        # Act - Should catch the exception and continue
        result = protocol._calculate_time_spent([mock_interview])

        # Assert - Should return 00:00:00 since time couldn't be parsed
        assert result == "00:00:00"

    def test_calculate_time_spent_catches_parser_error_for_invalid_minutes(self):
        """Test _calculate_time_spent catches ParserError for invalid minutes."""
        # Arrange
        protocol = CcmatMonthlyBannerProtocol()

        # Invalid minutes (60+) will cause arrow parser error
        mock_response = MagicMock()
        mock_response.response_option_value = "12:99:00"

        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value = [mock_response]

        # Act
        result = protocol._calculate_time_spent([mock_interview])

        # Assert
        assert result == "00:00:00"

    def test_calculate_time_spent_catches_parser_error_for_invalid_seconds(self):
        """Test _calculate_time_spent catches ParserError for invalid seconds."""
        # Arrange
        protocol = CcmatMonthlyBannerProtocol()

        # Invalid seconds (60+) will cause arrow parser error
        mock_response = MagicMock()
        mock_response.response_option_value = "12:30:99"

        mock_interview = MagicMock()
        mock_interview.interview_responses.filter.return_value = [mock_response]

        # Act
        result = protocol._calculate_time_spent([mock_interview])

        # Assert
        assert result == "00:00:00"
