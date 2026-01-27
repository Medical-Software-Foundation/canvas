"""Tests for DeleteCommandActionButton protocol."""
import pytest
from unittest.mock import MagicMock, patch

from delete_staged_commands_button.protocols.delete_command_action_button import DeleteCommandActionButton


class TestVisible:
    """Tests for visible method - button visibility logic."""

    def test_visible_always_returns_true(self):
        """Test that the delete button is always visible."""
        handler = DeleteCommandActionButton()

        assert handler.visible() is True


class TestHandle:
    """Tests for handle method - deleting staged commands."""

    def test_handle_deletes_single_staged_command(self, mock_event, mock_note):
        """Test deleting a single staged command."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        mock_command = MagicMock()
        mock_command.id = "cmd-uuid-123"
        mock_command.schema_key = "diagnose"
        mock_command.state = "staged"

        with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.filter.return_value.first.return_value = mock_note
                mock_cmd_objects.filter.return_value = [mock_command]

                effects = handler.handle()

                assert len(effects) == 1
                mock_note_objects.filter.assert_called_once_with(dbid="test-note-123")
                mock_cmd_objects.filter.assert_called_once_with(note=mock_note, state="staged")

    def test_handle_deletes_multiple_staged_commands(self, mock_event, mock_note):
        """Test deleting multiple staged commands of different types."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        mock_cmd1 = MagicMock()
        mock_cmd1.id = "cmd-uuid-1"
        mock_cmd1.schema_key = "diagnose"
        mock_cmd1.state = "staged"

        mock_cmd2 = MagicMock()
        mock_cmd2.id = "cmd-uuid-2"
        mock_cmd2.schema_key = "plan"
        mock_cmd2.state = "staged"

        mock_cmd3 = MagicMock()
        mock_cmd3.id = "cmd-uuid-3"
        mock_cmd3.schema_key = "vitals"
        mock_cmd3.state = "staged"

        with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.filter.return_value.first.return_value = mock_note
                mock_cmd_objects.filter.return_value = [mock_cmd1, mock_cmd2, mock_cmd3]

                effects = handler.handle()

                assert len(effects) == 3

    def test_handle_no_staged_commands_returns_empty(self, mock_event, mock_note):
        """Test that no effects are returned when there are no staged commands."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.filter.return_value.first.return_value = mock_note
                mock_cmd_objects.filter.return_value = []

                effects = handler.handle()

                assert len(effects) == 0

    def test_handle_all_command_types_in_schema_map(self, mock_event, mock_note):
        """Test that all command types in schema_map can be deleted."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        # Create commands for all schema_key types
        command_types = [
            "adjustPrescription", "allergy", "assess", "changeMedication", "closeGoal",
            "diagnose", "exam", "familyHistory", "followUp", "goal", "hpi",
            "imagingOrder", "imagingReview", "immunizationStatement", "instruct",
            "labOrder", "labReview", "medicalHistory", "medicationStatement",
            "perform", "plan", "prescribe", "questionnaire", "reasonForVisit",
            "refer", "referralReview", "refill", "removeAllergy", "resolveCondition",
            "ros", "stopMedication", "structuredAssessment", "surgicalHistory",
            "task", "uncategorizedDocumentReview", "updateDiagnosis", "updateGoal",
            "vitals"
        ]

        mock_commands = []
        for idx, cmd_type in enumerate(command_types):
            mock_cmd = MagicMock()
            mock_cmd.id = f"cmd-uuid-{idx}"
            mock_cmd.schema_key = cmd_type
            mock_cmd.state = "staged"
            mock_commands.append(mock_cmd)

        with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.filter.return_value.first.return_value = mock_note
                mock_cmd_objects.filter.return_value = mock_commands

                effects = handler.handle()

                # Should create delete effect for each command
                assert len(effects) == len(command_types)

    def test_handle_unsupported_command_type_logs_warning(self, mock_event, mock_note):
        """Test that unsupported command types log a warning."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        mock_cmd_unsupported = MagicMock()
        mock_cmd_unsupported.id = "cmd-uuid-999"
        mock_cmd_unsupported.schema_key = "unsupportedCommand"
        mock_cmd_unsupported.state = "staged"

        mock_cmd_supported = MagicMock()
        mock_cmd_supported.id = "cmd-uuid-1"
        mock_cmd_supported.schema_key = "diagnose"
        mock_cmd_supported.state = "staged"

        with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                with patch("delete_staged_commands_button.protocols.delete_command_action_button.log") as mock_log:
                    mock_note_objects.filter.return_value.first.return_value = mock_note
                    mock_cmd_objects.filter.return_value = [mock_cmd_unsupported, mock_cmd_supported]

                    effects = handler.handle()

                    # Only supported command should be deleted
                    assert len(effects) == 1
                    # Warning should be logged for unsupported command
                    mock_log.warning.assert_called_once()
                    assert "unsupportedCommand" in str(mock_log.warning.call_args)

    def test_handle_specific_command_types(self, mock_event, mock_note):
        """Test deleting specific common command types."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        test_cases = [
            ("diagnose", "Diagnose command"),
            ("prescribe", "Prescribe command"),
            ("labOrder", "Lab order command"),
            ("refer", "Refer command"),
            ("task", "Task command"),
            ("vitals", "Vitals command"),
        ]

        for schema_key, description in test_cases:
            mock_command = MagicMock()
            mock_command.id = f"cmd-uuid-{schema_key}"
            mock_command.schema_key = schema_key
            mock_command.state = "staged"

            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
                with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                    mock_note_objects.filter.return_value.first.return_value = mock_note
                    mock_cmd_objects.filter.return_value = [mock_command]

                    effects = handler.handle()

                    assert len(effects) == 1, f"Failed to delete {description}"

    def test_handle_only_deletes_staged_commands(self, mock_event, mock_note):
        """Test that only staged commands are deleted, not committed ones."""
        handler = DeleteCommandActionButton()
        handler.event = mock_event

        # This test verifies the filter is called with state="staged"
        with patch("delete_staged_commands_button.protocols.delete_command_action_button.Note.objects") as mock_note_objects:
            with patch("delete_staged_commands_button.protocols.delete_command_action_button.Command.objects") as mock_cmd_objects:
                mock_note_objects.filter.return_value.first.return_value = mock_note
                mock_cmd_objects.filter.return_value = []

                handler.handle()

                # Verify the filter was called with state="staged"
                call_args = mock_cmd_objects.filter.call_args
                assert call_args is not None
                assert call_args[1]['state'] == "staged"
                assert call_args[1]['note'] == mock_note


class TestButtonConfiguration:
    """Tests for button configuration constants."""

    def test_button_title(self):
        """Test button title is set correctly."""
        assert DeleteCommandActionButton.BUTTON_TITLE == "Delete All Staged Commands"

    def test_button_key(self):
        """Test button key is set correctly."""
        assert DeleteCommandActionButton.BUTTON_KEY == "DELETE_ALL_STAGED_COMMANDS"

    def test_button_location(self):
        """Test button location is set to note header."""
        from canvas_sdk.handlers.action_button import ActionButton
        assert DeleteCommandActionButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_HEADER
