from unittest.mock import Mock, patch, MagicMock
import pytest
from pydantic import ValidationError

from canvas_sdk.commands import (
    AllergyCommand,
    AssessCommand,
    DiagnoseCommand,
    QuestionnaireCommand,
)
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand
from canvas_sdk.commands.commands.immunization_statement import ImmunizationStatementCommand
from canvas_sdk.v1.data.note import NoteStates

from commit_all_commands_button.protocols.commit_all_commands import CommitButtonHandler


class TestCommitButtonHandlerVisibility:
    """Test cases for button visibility logic."""

    @patch("commit_all_commands_button.protocols.commit_all_commands.CurrentNoteStateEvent")
    def test_visible_when_note_not_locked(self, mock_note_state):
        """Button should be visible when note is not locked."""
        mock_note_event = Mock()
        mock_note_event.state = NoteStates.UNLOCKED
        mock_note_state.objects.get.return_value = mock_note_event

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        result = handler.visible()

        assert result is True
        mock_note_state.objects.get.assert_called_once_with(note__dbid="test-note-id")

    @patch("commit_all_commands_button.protocols.commit_all_commands.CurrentNoteStateEvent")
    def test_not_visible_when_note_locked(self, mock_note_state):
        """Button should not be visible when note is locked."""
        mock_note_event = Mock()
        mock_note_event.state = NoteStates.LOCKED
        mock_note_state.objects.get.return_value = mock_note_event

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        result = handler.visible()

        assert result is False
        mock_note_state.objects.get.assert_called_once_with(note__dbid="test-note-id")


class TestCommitButtonHandlerBasicCommit:
    """Test cases for basic command committing."""

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_commits_single_staged_command(self, mock_log, mock_command_model):
        """Handle should commit a single staged command."""
        mock_command = Mock()
        mock_command.schema_key = AllergyCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {}
        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(AllergyCommand, "__init__", return_value=None) as mock_init, \
             patch.object(AllergyCommand, "commit", return_value=Mock()) as mock_commit:
            effects = handler.handle()

            mock_command_model.objects.filter.assert_called_once_with(
                note_id="test-note-id", state="staged"
            )
            mock_init.assert_called_once_with(command_uuid="command-uuid-123")
            mock_commit.assert_called_once()
            assert len(effects) == 1
            mock_log.info.assert_called_once()

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_commits_multiple_staged_commands(self, mock_log, mock_command_model):
        """Handle should commit multiple staged commands."""
        mock_command1 = Mock()
        mock_command1.schema_key = AllergyCommand.Meta.key
        mock_command1.id = "command-uuid-1"
        mock_command1.data = {}

        mock_command2 = Mock()
        mock_command2.schema_key = AssessCommand.Meta.key
        mock_command2.id = "command-uuid-2"
        mock_command2.data = {}

        mock_command_model.objects.filter.return_value = [mock_command1, mock_command2]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(AllergyCommand, "__init__", return_value=None) as mock_allergy_init, \
             patch.object(AllergyCommand, "commit", return_value=Mock()) as mock_allergy_commit, \
             patch.object(AssessCommand, "__init__", return_value=None) as mock_assess_init, \
             patch.object(AssessCommand, "commit", return_value=Mock()) as mock_assess_commit:
            effects = handler.handle()

            mock_command_model.objects.filter.assert_called_once_with(
                note_id="test-note-id", state="staged"
            )
            mock_allergy_init.assert_called_once_with(command_uuid="command-uuid-1")
            mock_allergy_commit.assert_called_once()
            mock_assess_init.assert_called_once_with(command_uuid="command-uuid-2")
            mock_assess_commit.assert_called_once()
            assert len(effects) == 2

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    def test_handle_returns_empty_list_when_no_staged_commands(self, mock_command_model):
        """Handle should return empty list when no staged commands exist."""
        mock_command_model.objects.filter.return_value = []

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        effects = handler.handle()

        assert effects == []
        mock_command_model.objects.filter.assert_called_once_with(
            note_id="test-note-id", state="staged"
        )


class TestCommitButtonHandlerSpecialCases:
    """Test cases for special command types requiring extra parameters."""

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.Interview")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_questionnaire_command_with_interview(
        self, mock_log, mock_interview_model, mock_command_model
    ):
        """Handle should add questionnaire_id for Questionnaire commands."""
        mock_command = Mock()
        mock_command.schema_key = QuestionnaireCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.anchor_object_type = "interview"
        mock_command.anchor_object_dbid = "interview-dbid-123"
        mock_command.data = {}

        mock_questionnaire = Mock()
        mock_questionnaire.id = "questionnaire-id-456"
        mock_interview = Mock()
        mock_interview.questionnaires.first.return_value = mock_questionnaire
        mock_interview_model.objects.get.return_value = mock_interview

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(QuestionnaireCommand, "__init__", return_value=None) as mock_init, \
             patch.object(QuestionnaireCommand, "commit", return_value=Mock()) as mock_commit:
            effects = handler.handle()

            mock_interview_model.objects.get.assert_called_once_with(dbid="interview-dbid-123")
            mock_init.assert_called_once_with(
                command_uuid="command-uuid-123",
                questionnaire_id="questionnaire-id-456"
            )
            mock_commit.assert_called_once()
            assert len(effects) == 1

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_immunization_statement_with_cpt_and_cvx(
        self, mock_log, mock_command_model
    ):
        """Handle should extract CPT and CVX codes for ImmunizationStatement commands."""
        mock_command = Mock()
        mock_command.schema_key = ImmunizationStatementCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {
            "statement": {
                "extra": {
                    "coding": [
                        {"code": "90471", "system": "http://www.ama-assn.org/go/cpt"},
                        {"code": "03", "system": "http://hl7.org/fhir/sid/cvx"}
                    ]
                }
            }
        }

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(ImmunizationStatementCommand, "__init__", return_value=None) as mock_init, \
             patch.object(ImmunizationStatementCommand, "commit", return_value=Mock()) as mock_commit:
            effects = handler.handle()

            mock_init.assert_called_once_with(
                command_uuid="command-uuid-123",
                cpt_code="90471",
                cvx_code="03"
            )
            mock_commit.assert_called_once()
            assert len(effects) == 1

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_immunization_statement_with_missing_codes(
        self, mock_log, mock_command_model
    ):
        """Handle should use empty strings when CPT/CVX codes are missing."""
        mock_command = Mock()
        mock_command.schema_key = ImmunizationStatementCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {"statement": {"extra": {"coding": []}}}

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(ImmunizationStatementCommand, "__init__", return_value=None) as mock_init, \
             patch.object(ImmunizationStatementCommand, "commit", return_value=Mock()) as mock_commit:
            effects = handler.handle()

            mock_init.assert_called_once_with(
                command_uuid="command-uuid-123",
                cpt_code="",
                cvx_code=""
            )
            mock_commit.assert_called_once()
            assert len(effects) == 1

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.Medication")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_change_medication_command(
        self, mock_log, mock_medication_model, mock_command_model
    ):
        """Handle should add medication_id for ChangeMedication commands."""
        mock_command = Mock()
        mock_command.schema_key = ChangeMedicationCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {"medication": {"value": "medication-dbid-456"}}

        mock_medication = Mock()
        mock_medication.id = "medication-id-789"
        mock_medication_model.objects.get.return_value = mock_medication

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(ChangeMedicationCommand, "__init__", return_value=None) as mock_init, \
             patch.object(ChangeMedicationCommand, "commit", return_value=Mock()) as mock_commit:
            effects = handler.handle()

            mock_medication_model.objects.get.assert_called_once_with(dbid="medication-dbid-456")
            mock_init.assert_called_once_with(
                command_uuid="command-uuid-123",
                medication_id="medication-id-789"
            )
            mock_commit.assert_called_once()
            assert len(effects) == 1

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_change_medication_without_medication_value(
        self, mock_log, mock_command_model
    ):
        """Handle should handle ChangeMedication commands without medication value."""
        mock_command = Mock()
        mock_command.schema_key = ChangeMedicationCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {"medication": {}}

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(ChangeMedicationCommand, "__init__", return_value=None) as mock_init, \
             patch.object(ChangeMedicationCommand, "commit", return_value=Mock()) as mock_commit:
            effects = handler.handle()

            mock_init.assert_called_once_with(command_uuid="command-uuid-123")
            mock_commit.assert_called_once()
            assert len(effects) == 1


class TestCommitButtonHandlerErrorHandling:
    """Test cases for error handling."""

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_logs_validation_error(self, mock_log, mock_command_model):
        """Handle should log validation errors and continue processing."""
        mock_command = Mock()
        mock_command.schema_key = DiagnoseCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {}

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        validation_error = ValidationError.from_exception_data(
            "test",
            [{"type": "missing", "loc": ("field",), "msg": "Field required", "input": {}}]
        )

        with patch.object(DiagnoseCommand, "__init__", side_effect=validation_error):
            effects = handler.handle()

            assert len(effects) == 0
            mock_log.error.assert_called()
            assert mock_log.error.call_count == 2

    @patch("commit_all_commands_button.protocols.commit_all_commands.Command")
    @patch("commit_all_commands_button.protocols.commit_all_commands.log")
    def test_handle_logs_warning_for_unmapped_command(self, mock_log, mock_command_model):
        """Handle should log warning for unmapped command types."""
        mock_command = Mock()
        mock_command.schema_key = "unknown_command_type"
        mock_command.id = "command-uuid-123"
        mock_command.data = {}

        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        effects = handler.handle()

        assert len(effects) == 0
        mock_log.warning.assert_called_once()
        assert "not able to be committed" in mock_log.warning.call_args[0][0]


class TestCommitButtonHandlerConfiguration:
    """Test cases for handler configuration."""

    def test_button_title_is_correct(self):
        """Button should have correct title."""
        assert CommitButtonHandler.BUTTON_TITLE == "Commit All Commands"

    def test_button_key_is_correct(self):
        """Button should have correct key."""
        assert CommitButtonHandler.BUTTON_KEY == "COMMIT_ALL_COMMANDS"

    def test_button_location_is_note_footer(self):
        """Button should be located in note footer."""
        from canvas_sdk.handlers.action_button import ActionButton
        assert CommitButtonHandler.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_FOOTER

    def test_all_command_types_mapped(self):
        """All supported command types should be mapped."""
        expected_command_count = 27
        assert len(CommitButtonHandler.SCHEMA_KEYS_TO_COMMANDS) == expected_command_count
