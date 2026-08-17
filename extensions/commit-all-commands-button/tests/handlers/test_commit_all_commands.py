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

from commit_all_commands_button.handlers.commit_all_commands import CommitButtonHandler


@pytest.fixture(autouse=True)
def stub_reload():
    """Stub the note lookup and reload effect appended after a successful commit.

    Autouse because every test that commits something now gets the trailing
    ReloadNoteActionButtonsEffect, and neither the note lookup nor the effect's
    own validation is what those tests are about.
    """
    with patch("commit_all_commands_button.handlers.commit_all_commands.Note") as mock_note, patch(
        "commit_all_commands_button.handlers.commit_all_commands.ReloadNoteActionButtonsEffect"
    ) as mock_reload:
        mock_note.objects.get.return_value = Mock(id="note-uuid-abc")
        mock_reload.return_value.apply.return_value = Mock(name="reload_effect")
        yield mock_reload


class TestCommitButtonHandlerVisibility:
    """Test cases for button visibility logic."""

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.CurrentNoteStateEvent")
    def test_visible_when_note_not_locked_and_staged_commands_exist(
        self, mock_note_state, mock_command_model
    ):
        """Button should be visible when the note is unlocked and has staged commands."""
        mock_note_event = Mock()
        mock_note_event.state = NoteStates.UNLOCKED
        mock_note_state.objects.get.return_value = mock_note_event
        mock_command_model.objects.filter.return_value.exists.return_value = True

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        result = handler.visible()

        assert result is True
        mock_note_state.objects.get.assert_called_once_with(note__dbid="test-note-id")
        # Only the schema keys this button can actually commit are counted.
        _, kwargs = mock_command_model.objects.filter.call_args
        assert kwargs["note_id"] == "test-note-id"
        assert kwargs["state"] == "staged"
        assert set(kwargs["schema_key__in"]) == set(CommitButtonHandler.SCHEMA_KEYS_TO_COMMANDS)

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.CurrentNoteStateEvent")
    def test_not_visible_when_no_committable_staged_commands(
        self, mock_note_state, mock_command_model
    ):
        """An unlocked note with nothing this button can commit hides the button.

        Covers the case where a note holds only commands this button doesn't map
        — an unsent Prescribe, for instance — which would otherwise surface a
        button that does nothing.
        """
        mock_note_event = Mock()
        mock_note_event.state = NoteStates.UNLOCKED
        mock_note_state.objects.get.return_value = mock_note_event
        mock_command_model.objects.filter.return_value.exists.return_value = False

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        assert handler.visible() is False

    @patch("commit_all_commands_button.handlers.commit_all_commands.CurrentNoteStateEvent")
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

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 2
            mock_log.info.assert_called_once()

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 3

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
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

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.Interview")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 2

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 2

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 2

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.Medication")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 2

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
            # commit effect(s) plus the trailing ReloadNoteActionButtonsEffect
            assert len(effects) == 2


class TestCommitButtonHandlerErrorHandling:
    """Test cases for error handling."""

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
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
        """The mapping contains exactly the commands this button commits.

        Asserted as a set of schema keys rather than a count. A bare count went
        stale silently when the four review commands were added — it still read
        27 against a map of 31 — and a count also can't say *which* command is
        missing when it fails.

        Commands deliberately absent, and why:
          - prescribe / refill / adjustPrescription / imagingOrder: ordering
            commands that have to be sent, not merely committed.
          - refer: has a delegate, so a staged Refer doesn't imply the provider
            meant to commit it.
          - labOrder: committable, but an order — same reasoning as above.
          - reasonForVisit: its commit interpreter is commented out in home-app,
            so the effect is not honored.
          - reference: committed on origination, so it never sits staged.
          - chartSectionReview / customCommand: no COMMIT effect in the SDK.
        """
        expected_schema_keys = {
            "allergy",
            "assess",
            "changeMedication",
            "closeGoal",
            "diagnose",
            "exam",
            "familyHistory",
            "followUp",
            "goal",
            "hpi",
            "imagingReview",
            "immunizationStatement",
            "instruct",
            "labReview",
            "medicalHistory",
            "medicationStatement",
            "perform",
            "plan",
            "pocLabTest",
            "questionnaire",
            "referralReview",
            "removeAllergy",
            "resolveCondition",
            "ros",
            "stopMedication",
            "structuredAssessment",
            "surgicalHistory",
            "task",
            "uncategorizedDocumentReview",
            "updateDiagnosis",
            "updateGoal",
            "vitals",
        }
        assert set(CommitButtonHandler.SCHEMA_KEYS_TO_COMMANDS) == expected_schema_keys


class TestCommitButtonHandlerReload:
    """Test cases for the button-reload effect appended after committing."""

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
    def test_reload_effect_appended_last_after_committing(
        self, mock_log, mock_command_model, stub_reload
    ):
        """A successful commit appends exactly one reload effect, in last place.

        Order matters: effects apply sequentially, so the reload has to come
        after the commits or it re-evaluates visibility against the old state.
        """
        mock_command = Mock()
        mock_command.schema_key = AllergyCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {}
        mock_command_model.objects.filter.return_value = [mock_command]

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        with patch.object(AllergyCommand, "__init__", return_value=None), patch.object(
            AllergyCommand, "commit", return_value=Mock(name="commit_effect")
        ):
            effects = handler.handle()

        stub_reload.assert_called_once_with(id="note-uuid-abc")
        assert effects[-1] is stub_reload.return_value.apply.return_value
        assert len(effects) == 2

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    def test_no_reload_effect_when_nothing_committed(self, mock_command_model, stub_reload):
        """With nothing to commit, no reload is requested.

        Visibility can't have changed, so the round trip would be wasted.
        """
        mock_command_model.objects.filter.return_value = []

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        assert handler.handle() == []
        stub_reload.assert_not_called()
