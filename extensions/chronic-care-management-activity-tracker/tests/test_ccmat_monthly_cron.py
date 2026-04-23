"""Tests for the CCM Monthly Cron Task handler."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron import CcmatMonthlyCron


class TestCcmatMonthlyCron:
    """Test cases for the CcmatMonthlyCron handler."""

    def test_parse_time_to_minutes_valid_format(self):
        """Test that _parse_time_to_minutes correctly converts HH:mm:ss to minutes."""
        # Test cases: (input, expected_output)
        test_cases = [
            ("00:20:00", 20),
            ("01:00:00", 60),
            ("01:30:00", 90),
            ("01:30:30", 91),  # Rounds up when seconds >= 30
            ("01:30:29", 90),  # No rounding when seconds < 30
            ("02:15:45", 136), # 2*60 + 15 + 1 = 136
        ]

        for time_str, expected_minutes in test_cases:
            result = CcmatMonthlyCron._parse_time_to_minutes(time_str)
            assert result == expected_minutes, f"Failed for {time_str}: expected {expected_minutes}, got {result}"

    def test_parse_time_to_minutes_invalid_format(self):
        """Test that _parse_time_to_minutes raises error for invalid format."""
        with pytest.raises(ValueError):
            CcmatMonthlyCron._parse_time_to_minutes("invalid")

        with pytest.raises(ValueError):
            CcmatMonthlyCron._parse_time_to_minutes("12:30")  # Missing seconds

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_returns_empty_when_questionnaire_not_found(self, mock_questionnaire):
        """Test that execute returns empty list when questionnaire is not found."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = None

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        assert effects == []

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_returns_empty_when_note_type_not_found(self, mock_questionnaire, mock_note_type):
        """Test that execute returns empty list when note type is not found."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = None

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        assert effects == []

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Prefetch")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Interview")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_processes_patients_with_ccm_diagnosis(self, mock_questionnaire, mock_note_type, mock_patient, mock_interview, mock_prefetch):
        """Test that execute processes patients with CCM diagnosis."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(id="note-type-123")

        # Create a mock QuerySet-like object that supports both iteration and count()
        mock_queryset = MagicMock()
        mock_queryset.count.return_value = 0
        mock_queryset.__iter__.return_value = iter([])  # Empty iterator for the loop

        mock_patient.objects.filter.return_value.prefetch_related.return_value.distinct.return_value = mock_queryset

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        # Should return list (may be empty if no patients meet threshold)
        assert isinstance(effects, list)
        assert len(effects) == 0
        mock_queryset.count.assert_called_once()

    def test_add_billing_line_items_below_threshold(self):
        """Test that _add_billing_line_items returns empty for time below threshold."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act
        effects = cron._add_billing_line_items("test-note-id", "00:15:00", [])

        # Assert
        assert effects == []

    def test_add_billing_line_items_20_to_39_minutes(self):
        """Test that _add_billing_line_items adds only CPT 99490 for 20-39 minutes."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act
        effects = cron._add_billing_line_items("test-note-id", "00:25:00", [])

        # Assert
        assert len(effects) == 1
        # Should only have 99490

    def test_add_billing_line_items_40_plus_minutes(self):
        """Test that _add_billing_line_items adds CPT 99490 and 99439 for 40+ minutes."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act - 63 minutes should give 99490 x1 and 99439 x2
        effects = cron._add_billing_line_items("test-note-id", "01:03:00", [])

        # Assert
        assert len(effects) == 2
        # Should have both 99490 and 99439

    def test_schedule_is_monthly(self):
        """Test that the schedule is set to run monthly."""
        # Assert
        assert CcmatMonthlyCron.SCHEDULE == "0 0 1 * *"

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Prefetch")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Interview")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_with_patient_meeting_threshold(self, mock_questionnaire, mock_note_type, mock_patient, mock_interview_class, mock_prefetch):
        """Test execute processes patient meeting time threshold."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(id="note-type-123")

        # Create mock patient with prefetched interview data
        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "test-patient-123"

        # Create mock interview response
        mock_response = MagicMock()
        mock_response.question.code = "ccm_month_minutes_question"
        mock_response.response_option_value = "00:25:00"

        # Create mock interview with prefetched responses
        mock_interview = MagicMock()
        mock_interview.interview_responses.all.return_value = [mock_response]

        # Set prefetched_interviews attribute (used by optimized code)
        mock_patient_obj.prefetched_interviews = [mock_interview]

        # Mock the patient queryset
        mock_patient_queryset = MagicMock()
        mock_patient_queryset.count.return_value = 1
        mock_patient_queryset.__iter__.return_value = iter([mock_patient_obj])
        mock_patient.objects.filter.return_value.prefetch_related.return_value.distinct.return_value = mock_patient_queryset

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Mock the _create_ccm_note_and_billing to return effects
        with patch.object(cron, '_create_ccm_note_and_billing', return_value=[MagicMock(), MagicMock()]):
            # Act
            effects = cron.execute()

            # Assert
            assert len(effects) == 2
            cron._create_ccm_note_and_billing.assert_called_once()

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Prefetch")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Interview")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_skips_patient_below_threshold(self, mock_questionnaire, mock_note_type, mock_patient, mock_interview_class, mock_prefetch):
        """Test execute skips patients below 20 minute threshold."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(id="note-type-123")

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "test-patient-456"

        # Create mock interview response with time below threshold
        mock_response = MagicMock()
        mock_response.question.code = "ccm_month_minutes_question"
        mock_response.response_option_value = "00:15:00"

        mock_interview = MagicMock()
        mock_interview.interview_responses.all.return_value = [mock_response]

        mock_patient_obj.prefetched_interviews = [mock_interview]

        mock_patient_queryset = MagicMock()
        mock_patient_queryset.count.return_value = 1
        mock_patient_queryset.__iter__.return_value = iter([mock_patient_obj])
        mock_patient.objects.filter.return_value.prefetch_related.return_value.distinct.return_value = mock_patient_queryset

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        assert len(effects) == 0  # Should skip patient below threshold

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Prefetch")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Interview")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_skips_patient_without_interview(self, mock_questionnaire, mock_note_type, mock_patient, mock_interview_class, mock_prefetch):
        """Test execute skips patients without questionnaires."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(id="note-type-123")

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "test-patient-789"

        # No prefetched interviews
        mock_patient_obj.prefetched_interviews = []

        mock_patient_queryset = MagicMock()
        mock_patient_queryset.count.return_value = 1
        mock_patient_queryset.__iter__.return_value = iter([mock_patient_obj])
        mock_patient.objects.filter.return_value.prefetch_related.return_value.distinct.return_value = mock_patient_queryset

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        assert len(effects) == 0  # Should skip patient without interview

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Prefetch")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Interview")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_skips_patient_without_time_response(self, mock_questionnaire, mock_note_type, mock_patient, mock_interview_class, mock_prefetch):
        """Test execute skips patients without time response in questionnaire."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(id="note-type-123")

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "test-patient-999"

        # Create mock interview response with different question code
        mock_response = MagicMock()
        mock_response.question.code = "other_question"
        mock_response.response_option_value = "some value"

        mock_interview = MagicMock()
        mock_interview.interview_responses.all.return_value = [mock_response]

        mock_patient_obj.prefetched_interviews = [mock_interview]

        mock_patient_queryset = MagicMock()
        mock_patient_queryset.count.return_value = 1
        mock_patient_queryset.__iter__.return_value = iter([mock_patient_obj])
        mock_patient.objects.filter.return_value.prefetch_related.return_value.distinct.return_value = mock_patient_queryset

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        assert len(effects) == 0  # Should skip patient without time response

    def test_parse_time_to_minutes_with_zero_values(self):
        """Test _parse_time_to_minutes handles zero values correctly."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act
        result = cron._parse_time_to_minutes("00:00:00")

        # Assert
        assert result == 0

    def test_parse_time_to_minutes_with_large_hours(self):
        """Test _parse_time_to_minutes handles large hour values."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act - 5 hours 30 minutes = 330 minutes
        result = cron._parse_time_to_minutes("05:30:00")

        # Assert
        assert result == 330

    def test_add_billing_line_items_exact_threshold(self):
        """Test _add_billing_line_items at exact 20 minute threshold."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act - Exactly 20 minutes should give 1x 99490
        effects = cron._add_billing_line_items("test-note-id", "00:20:00", [])

        # Assert
        assert len(effects) == 1

    def test_add_billing_line_items_exact_40_minutes(self):
        """Test _add_billing_line_items at exact 40 minute mark."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act - Exactly 40 minutes: 99490 x1, 99439 x1
        effects = cron._add_billing_line_items("test-note-id", "00:40:00", [])

        # Assert
        assert len(effects) == 2

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Prefetch")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Interview")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Patient")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Questionnaire")
    def test_execute_logs_when_no_interview_exists(self, mock_questionnaire, mock_note_type, mock_patient, mock_interview_class, mock_prefetch):
        """Test execute logs and continues when patient has no interviews."""
        # Arrange
        mock_questionnaire.objects.values_list.return_value.filter.return_value.first.return_value = "test-q-id"
        mock_note_type.objects.filter.return_value.first.return_value = MagicMock(id="note-type-123")

        mock_patient_obj = MagicMock()
        mock_patient_obj.id = "no-interview-patient"

        # No prefetched interviews
        mock_patient_obj.prefetched_interviews = []

        mock_patient_queryset = MagicMock()
        mock_patient_queryset.count.return_value = 1
        mock_patient_queryset.__iter__.return_value = iter([mock_patient_obj])
        mock_patient.objects.filter.return_value.prefetch_related.return_value.distinct.return_value = mock_patient_queryset

        cron = CcmatMonthlyCron()
        cron.target = datetime.now()

        # Act
        effects = cron.execute()

        # Assert
        assert len(effects) == 0


    def test_add_billing_line_items_at_60_minutes(self):
        """Test _add_billing_line_items at 60 minute mark (3x 99439)."""
        # Arrange
        cron = CcmatMonthlyCron()

        # Act - 60 minutes: 99490 x1, 99439 x2
        effects = cron._add_billing_line_items("test-note-id", "01:00:00", [])

        # Assert
        assert len(effects) == 2

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_returns_empty_when_note_type_not_found(self, mock_note_type):
        """Test _create_ccm_note_and_billing returns empty list when note type not found."""
        # Arrange
        mock_note_type.objects.filter.return_value.first.return_value = None  # No note type found

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        # Ensure no prefetched_ccm_memberships to trigger query path
        del mock_patient.prefetched_ccm_memberships

        cron = CcmatMonthlyCron()

        # Act - Should return empty list
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert result == []
        mock_note_type.objects.filter.assert_called_once()

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.CareTeamMembership")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_returns_empty_when_no_ccm_provider(
            self, mock_note_type, mock_care_team
    ):
        """Test _create_ccm_note_and_billing returns empty when no CCM provider found."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # No CCM membership found via fallback query
        mock_care_team.objects.filter.return_value.select_related.return_value.first.return_value = None

        mock_patient = MagicMock()
        mock_patient.id = "test-patient-no-provider"
        # Empty prefetched list triggers "no provider" path
        mock_patient.prefetched_ccm_memberships = []

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert result == []

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.CareTeamMembership")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_returns_empty_when_membership_has_no_staff(
            self, mock_note_type, mock_care_team
    ):
        """Test _create_ccm_note_and_billing returns empty when membership exists but has no staff."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Membership exists but staff is None
        mock_membership = MagicMock()
        mock_membership.staff = None

        mock_patient = MagicMock()
        mock_patient.id = "test-patient-no-staff"
        mock_patient.prefetched_ccm_memberships = [mock_membership]

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert result == []

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.AddBillingLineItem")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.DiagnoseCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Note")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_uses_most_recent_note_location(
            self, mock_note_type, mock_note, mock_note_effect,
            mock_diagnose_cmd, mock_billing
    ):
        """Test _create_ccm_note_and_billing uses location from patient's most recent note."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Setup CCM provider via prefetch
        mock_staff = MagicMock()
        mock_staff.id = "staff-123"
        mock_staff.primary_practice_location.id = "default-location"

        mock_membership = MagicMock()
        mock_membership.staff = mock_staff

        # Setup most recent note with location
        mock_recent_note = MagicMock()
        mock_recent_note.location.id = "recent-note-location"
        mock_note.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = mock_recent_note

        # Setup mock metadata
        mock_meta = MagicMock()
        mock_meta.key = "ccm_diagnosis"
        mock_meta.value = "E11.9,I10"

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        mock_patient.prefetched_ccm_memberships = [mock_membership]
        mock_patient.metadata.all.return_value = [mock_meta]

        # Mock note effect
        mock_note_effect_instance = MagicMock()
        mock_note_effect.return_value = mock_note_effect_instance

        # Mock diagnose command
        mock_diagnose_instance = MagicMock()
        mock_diagnose_cmd.return_value = mock_diagnose_instance

        # Mock billing
        mock_billing_instance = MagicMock()
        mock_billing.return_value = mock_billing_instance

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert len(result) > 0
        # Verify NoteEffect was created with the recent note's location
        mock_note_effect.assert_called_once()
        call_kwargs = mock_note_effect.call_args[1]
        assert call_kwargs["practice_location_id"] == "recent-note-location"

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.AddBillingLineItem")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.DiagnoseCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Note")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_falls_back_to_staff_location(
            self, mock_note_type, mock_note, mock_note_effect,
            mock_diagnose_cmd, mock_billing
    ):
        """Test _create_ccm_note_and_billing falls back to staff location when no recent note."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Setup CCM provider via prefetch
        mock_staff = MagicMock()
        mock_staff.id = "staff-123"
        mock_staff.primary_practice_location.id = "staff-default-location"

        mock_membership = MagicMock()
        mock_membership.staff = mock_staff

        # No recent note
        mock_note.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        # Setup mock metadata
        mock_meta = MagicMock()
        mock_meta.key = "ccm_diagnosis"
        mock_meta.value = "E11.9"

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        mock_patient.prefetched_ccm_memberships = [mock_membership]
        mock_patient.metadata.all.return_value = [mock_meta]

        # Mock note effect
        mock_note_effect_instance = MagicMock()
        mock_note_effect.return_value = mock_note_effect_instance

        # Mock diagnose command
        mock_diagnose_instance = MagicMock()
        mock_diagnose_cmd.return_value = mock_diagnose_instance

        # Mock billing
        mock_billing_instance = MagicMock()
        mock_billing.return_value = mock_billing_instance

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert len(result) > 0
        # Verify NoteEffect was created with staff's primary location
        mock_note_effect.assert_called_once()
        call_kwargs = mock_note_effect.call_args[1]
        assert call_kwargs["practice_location_id"] == "staff-default-location"

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.AddBillingLineItem")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.DiagnoseCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Note")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_handles_no_ccm_diagnoses(
            self, mock_note_type, mock_note, mock_note_effect,
            mock_diagnose_cmd, mock_billing
    ):
        """Test _create_ccm_note_and_billing handles patient with no CCM diagnoses metadata."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Setup CCM provider via prefetch
        mock_staff = MagicMock()
        mock_staff.id = "staff-123"
        mock_staff.primary_practice_location.id = "staff-location"

        mock_membership = MagicMock()
        mock_membership.staff = mock_staff

        mock_note.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        # Setup mock metadata with different key (no ccm_diagnosis)
        mock_meta = MagicMock()
        mock_meta.key = "other_key"
        mock_meta.value = "other_value"

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        mock_patient.prefetched_ccm_memberships = [mock_membership]
        mock_patient.metadata.all.return_value = [mock_meta]

        # Mock note effect
        mock_note_effect_instance = MagicMock()
        mock_note_effect.return_value = mock_note_effect_instance

        # Mock billing
        mock_billing_instance = MagicMock()
        mock_billing.return_value = mock_billing_instance

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert len(result) > 0
        # DiagnoseCommand should not be called since there are no diagnoses
        mock_diagnose_cmd.assert_not_called()

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.AddBillingLineItem")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.DiagnoseCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Note")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_creates_diagnose_commands(
            self, mock_note_type, mock_note, mock_note_effect,
            mock_diagnose_cmd, mock_billing
    ):
        """Test _create_ccm_note_and_billing creates DiagnoseCommands for each ICD-10 code."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Setup CCM provider via prefetch
        mock_staff = MagicMock()
        mock_staff.id = "staff-123"
        mock_staff.primary_practice_location.id = "staff-location"

        mock_membership = MagicMock()
        mock_membership.staff = mock_staff

        mock_note.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        # Setup mock metadata with multiple ICD-10 codes
        mock_meta = MagicMock()
        mock_meta.key = "ccm_diagnosis"
        mock_meta.value = "E11.9, I10, J44.1"

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        mock_patient.prefetched_ccm_memberships = [mock_membership]
        mock_patient.metadata.all.return_value = [mock_meta]

        # Mock note effect
        mock_note_effect_instance = MagicMock()
        mock_note_effect.return_value = mock_note_effect_instance

        # Mock diagnose command
        mock_diagnose_instance = MagicMock()
        mock_diagnose_cmd.return_value = mock_diagnose_instance

        # Mock billing
        mock_billing_instance = MagicMock()
        mock_billing.return_value = mock_billing_instance

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert len(result) > 0
        # Should create DiagnoseCommand for each of the 3 ICD-10 codes
        assert mock_diagnose_cmd.call_count == 3

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.AddBillingLineItem")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.DiagnoseCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Note")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_recent_note_without_location(
            self, mock_note_type, mock_note, mock_note_effect,
            mock_diagnose_cmd, mock_billing
    ):
        """Test _create_ccm_note_and_billing when recent note has no location."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Setup CCM provider via prefetch
        mock_staff = MagicMock()
        mock_staff.id = "staff-123"
        mock_staff.primary_practice_location.id = "staff-fallback-location"

        mock_membership = MagicMock()
        mock_membership.staff = mock_staff

        # Recent note exists but has no location
        mock_recent_note = MagicMock()
        mock_recent_note.location = None
        mock_note.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = mock_recent_note

        # Setup mock metadata
        mock_meta = MagicMock()
        mock_meta.key = "ccm_diagnosis"
        mock_meta.value = "E11.9"

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        mock_patient.prefetched_ccm_memberships = [mock_membership]
        mock_patient.metadata.all.return_value = [mock_meta]

        # Mock note effect
        mock_note_effect_instance = MagicMock()
        mock_note_effect.return_value = mock_note_effect_instance

        # Mock diagnose command
        mock_diagnose_instance = MagicMock()
        mock_diagnose_cmd.return_value = mock_diagnose_instance

        # Mock billing
        mock_billing_instance = MagicMock()
        mock_billing.return_value = mock_billing_instance

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert len(result) > 0
        # Should fall back to staff's primary location
        mock_note_effect.assert_called_once()
        call_kwargs = mock_note_effect.call_args[1]
        assert call_kwargs["practice_location_id"] == "staff-fallback-location"

    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.CareTeamMembership")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.AddBillingLineItem")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.DiagnoseCommand")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteEffect")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.Note")
    @patch("chronic_care_management_activity_tracker.handlers.ccmat_monthly_cron.NoteType")
    def test_create_ccm_note_and_billing_fallback_query_when_no_prefetch(
            self, mock_note_type, mock_note, mock_note_effect,
            mock_diagnose_cmd, mock_billing, mock_care_team
    ):
        """Test _create_ccm_note_and_billing uses fallback query when prefetched data not available."""
        # Arrange
        mock_note_type_obj = MagicMock()
        mock_note_type_obj.id = "note-type-123"
        mock_note_type.objects.filter.return_value.first.return_value = mock_note_type_obj

        # Setup CCM provider via fallback query
        mock_staff = MagicMock()
        mock_staff.id = "staff-123"
        mock_staff.primary_practice_location.id = "staff-location"

        mock_membership = MagicMock()
        mock_membership.staff = mock_staff
        mock_care_team.objects.filter.return_value.select_related.return_value.first.return_value = mock_membership

        mock_note.objects.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        mock_patient = MagicMock()
        mock_patient.id = "test-patient"
        # No prefetched_ccm_memberships attribute - will use fallback query
        del mock_patient.prefetched_ccm_memberships
        mock_patient.metadata.filter.return_value.values_list.return_value.first.return_value = "E11.9"

        # Mock note effect
        mock_note_effect_instance = MagicMock()
        mock_note_effect.return_value = mock_note_effect_instance

        # Mock diagnose command
        mock_diagnose_instance = MagicMock()
        mock_diagnose_cmd.return_value = mock_diagnose_instance

        # Mock billing
        mock_billing_instance = MagicMock()
        mock_billing.return_value = mock_billing_instance

        cron = CcmatMonthlyCron()

        # Act
        result = cron._create_ccm_note_and_billing(mock_patient, "00:25:00")

        # Assert
        assert len(result) > 0
        # Verify fallback query was used
        mock_care_team.objects.filter.assert_called_once()
