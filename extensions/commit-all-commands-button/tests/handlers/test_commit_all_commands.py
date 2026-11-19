from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
import pytest
from pydantic import ValidationError

from canvas_sdk.commands import (
    AllergyCommand,
    AssessCommand,
    DiagnoseCommand,
    FollowUpCommand,
    HistoryOfPresentIllnessCommand,
    QuestionnaireCommand,
)
from canvas_sdk.commands.commands.change_medication import ChangeMedicationCommand
from canvas_sdk.commands.commands.immunization_statement import ImmunizationStatementCommand

from commit_all_commands_button.handlers.commit_all_commands import (
    NOT_IN_NOTE,
    CommitButtonHandler,
)

MODULE = "commit_all_commands_button.handlers.commit_all_commands"


class AnyUUID:
    """A body UUID set containing every command, for tests not about body placement."""

    def __contains__(self, item: object) -> bool:
        return True


@pytest.fixture(autouse=True)
def note_checks():
    """Stub the note lookup, note checks and modal rendering so each test controls them."""
    with patch(f"{MODULE}.Note") as mock_note_model, \
         patch.object(CommitButtonHandler, "accepts_commits", return_value=True) as accepts, \
         patch.object(CommitButtonHandler, "command_uuids_in_body", return_value=AnyUUID()) as in_body, \
         patch(f"{MODULE}.render_to_string", return_value="<p>summary</p>") as render:
        yield SimpleNamespace(
            note_model=mock_note_model, accepts=accepts, in_body=in_body, render=render
        )


def make_handler(note_id: str = "test-note-id") -> CommitButtonHandler:
    mock_event = Mock()
    mock_event.context = {"note_id": note_id}
    return CommitButtonHandler(event=mock_event)


def make_command(schema_key: str, command_id: str, data: dict | None = None) -> Mock:
    command = Mock()
    command.schema_key = schema_key
    command.id = command_id
    command.data = data
    return command


class TestCommitButtonHandlerVisibility:
    """Test cases for button visibility logic."""

    @pytest.mark.parametrize("accepts", [True, False])
    def test_visible_follows_accepts_commits(self, note_checks, accepts):
        """The button shows exactly when the note accepts commits."""
        note_checks.accepts.return_value = accepts

        assert make_handler().visible() is accepts
        note_checks.note_model.objects.select_related.return_value.get.assert_called_once_with(
            dbid="test-note-id"
        )


class TestCommitButtonHandlerBasicCommit:
    """Test cases for basic command committing."""

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
    def test_handle_commits_single_staged_command(self, mock_log, mock_command_model):
        """Handle should commit a single staged command."""
        mock_command = Mock()
        mock_command.schema_key = AllergyCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {"allergy": {"value": 1}}
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

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
    def test_handle_commits_multiple_staged_commands(self, mock_log, mock_command_model):
        """Handle should commit multiple staged commands."""
        mock_command1 = Mock()
        mock_command1.schema_key = AllergyCommand.Meta.key
        mock_command1.id = "command-uuid-1"
        mock_command1.data = {"allergy": {"value": 1}}

        mock_command2 = Mock()
        mock_command2.schema_key = AssessCommand.Meta.key
        mock_command2.id = "command-uuid-2"
        mock_command2.data = {"condition": {"value": 1}}

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

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    def test_handle_returns_empty_list_when_no_staged_commands(
        self, mock_command_model, note_checks
    ):
        """Handle should return empty list when no staged commands exist."""
        mock_command_model.objects.filter.return_value = []

        mock_event = Mock()
        mock_event.context = {"note_id": "test-note-id"}
        handler = CommitButtonHandler(event=mock_event)

        effects = handler.handle()

        assert effects == []
        note_checks.render.assert_not_called()
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
            assert len(effects) == 1

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
            assert len(effects) == 1

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
            assert len(effects) == 1

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
            assert len(effects) == 1

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
            assert len(effects) == 1


class TestCommitButtonHandlerErrorHandling:
    """Test cases for error handling."""

    @patch("commit_all_commands_button.handlers.commit_all_commands.Command")
    @patch("commit_all_commands_button.handlers.commit_all_commands.log")
    def test_handle_logs_validation_error(self, mock_log, mock_command_model):
        """Handle should log validation errors and continue processing."""
        mock_command = Mock()
        mock_command.schema_key = DiagnoseCommand.Meta.key
        mock_command.id = "command-uuid-123"
        mock_command.data = {"diagnose": {"value": "E11.9"}}

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


class TestCommitButtonHandlerSkipping:
    """Test cases for commands the button leaves uncommitted."""

    @patch(f"{MODULE}.Command")
    def test_handle_commits_nothing_when_note_rejects_commits(self, mock_command_model, note_checks):
        """A note that rejects commits gets no effects, and its commands are not queried."""
        note_checks.accepts.return_value = False

        assert make_handler().handle() == []
        mock_command_model.objects.filter.assert_not_called()

    @patch(f"{MODULE}.render_to_string", return_value="<p>skipped</p>")
    @patch(f"{MODULE}.Command")
    def test_handle_skips_command_not_in_body(self, mock_command_model, mock_render, note_checks):
        """A staged command missing from the note body is not committed and is listed."""
        note_checks.in_body.return_value = {"inbody"}
        mock_command_model.objects.filter.return_value = [
            make_command(AllergyCommand.Meta.key, "in-body", {"allergy": {"value": 1}}),
            make_command(AllergyCommand.Meta.key, "orphan", {"allergy": {"value": 2}}),
        ]

        with patch.object(AllergyCommand, "__init__", return_value=None) as mock_init, \
             patch.object(AllergyCommand, "commit", return_value=Mock()):
            effects = make_handler().handle()

        mock_init.assert_called_once_with(command_uuid="in-body")
        assert len(effects) == 2
        mock_render.assert_called_once_with(
            "templates/skipped_commands.html",
            {"skipped": [{"label": "Allergy", "reason": NOT_IN_NOTE}]},
        )

    @pytest.mark.parametrize(
        "narrative", [None, "", "   \n ", "missing"],
    )
    @patch(f"{MODULE}.render_to_string", return_value="<p>skipped</p>")
    @patch(f"{MODULE}.Command")
    def test_handle_skips_hpi_with_blank_narrative(
        self, mock_command_model, mock_render, narrative
    ):
        """An HPI with an empty or absent narrative is not committed and is listed."""
        data = {} if narrative == "missing" else {"narrative": narrative}
        mock_command_model.objects.filter.return_value = [
            make_command(HistoryOfPresentIllnessCommand.Meta.key, "hpi-1", data),
        ]

        with patch.object(HistoryOfPresentIllnessCommand, "commit") as mock_commit:
            effects = make_handler().handle()

        mock_commit.assert_not_called()
        assert len(effects) == 1
        mock_render.assert_called_once_with(
            "templates/skipped_commands.html",
            {
                "skipped": [
                    {"label": "History Of Present Illness", "reason": "Empty required field: Narrative"}
                ]
            },
        )

    @patch(f"{MODULE}.render_to_string", return_value="<p>summary</p>")
    @patch(f"{MODULE}.Command")
    def test_handle_commits_hpi_with_narrative(self, mock_command_model, mock_render):
        """An HPI with a narrative is committed and no modal is shown."""
        mock_command_model.objects.filter.return_value = [
            make_command(HistoryOfPresentIllnessCommand.Meta.key, "hpi-1", {"narrative": "Headache x3d"}),
        ]

        with patch.object(HistoryOfPresentIllnessCommand, "__init__", return_value=None), \
             patch.object(HistoryOfPresentIllnessCommand, "commit", return_value=Mock()) as mock_commit:
            effects = make_handler().handle()

        mock_commit.assert_called_once()
        assert len(effects) == 1
        mock_render.assert_not_called()

    @pytest.mark.parametrize(
        "data, reason",
        [
            ({"requested_date": {"date": "2026-12-01"}, "note_type": {}}, "Empty required field: Visit Type"),
            ({"requested_date": None, "note_type": {"value": 1}}, "Empty required field: Requested date"),
            ({}, "Empty required fields: Requested date, Visit Type"),
        ],
    )
    @patch(f"{MODULE}.render_to_string", return_value="<p>skipped</p>")
    @patch(f"{MODULE}.Command")
    def test_handle_skips_follow_up_naming_each_empty_field(
        self, mock_command_model, mock_render, data, reason
    ):
        """Every required field is checked, and each empty one is named by its label."""
        mock_command_model.objects.filter.return_value = [
            make_command(FollowUpCommand.Meta.key, "fu-1", data),
        ]

        with patch.object(FollowUpCommand, "commit") as mock_commit:
            make_handler().handle()

        mock_commit.assert_not_called()
        assert mock_render.call_args.args[1]["skipped"] == [{"label": "Follow Up", "reason": reason}]

    @patch(f"{MODULE}.render_to_string", return_value="<p>skipped</p>")
    @patch(f"{MODULE}.Command")
    def test_handle_skips_command_with_no_data(self, mock_command_model, mock_render):
        """A command whose data is null is treated as having every field empty."""
        mock_command_model.objects.filter.return_value = [
            make_command(DiagnoseCommand.Meta.key, "dx-1", None),
        ]

        with patch.object(DiagnoseCommand, "commit") as mock_commit:
            make_handler().handle()

        mock_commit.assert_not_called()
        assert mock_render.call_args.args[1]["skipped"] == [
            {"label": "Diagnose", "reason": "Empty required field: Diagnose"}
        ]

    @patch(f"{MODULE}.Command")
    def test_handle_does_not_precheck_commands_given_values_at_commit(self, mock_command_model):
        """Change Medication is committed with its values, so empty data does not skip it."""
        mock_command_model.objects.filter.return_value = [
            make_command(ChangeMedicationCommand.Meta.key, "cm-1", {}),
        ]

        with patch.object(ChangeMedicationCommand, "__init__", return_value=None), \
             patch.object(ChangeMedicationCommand, "commit", return_value=Mock()) as mock_commit:
            make_handler().handle()

        mock_commit.assert_called_once()

    @patch(f"{MODULE}.render_to_string", return_value="<p>skipped</p>")
    @patch(f"{MODULE}.Command")
    def test_handle_returns_launch_modal_effect_listing_skips(self, mock_command_model, mock_render):
        """The skipped list is a default modal carrying the rendered template."""
        mock_command_model.objects.filter.return_value = [
            make_command(HistoryOfPresentIllnessCommand.Meta.key, "hpi-1", {"narrative": ""}),
        ]

        effects = make_handler().handle()

        assert len(effects) == 1
        assert '"content": "<p>skipped</p>"' in effects[0].payload
        assert '"target": "default_modal"' in effects[0].payload
        assert '"title": "Some commands were not committed"' in effects[0].payload
