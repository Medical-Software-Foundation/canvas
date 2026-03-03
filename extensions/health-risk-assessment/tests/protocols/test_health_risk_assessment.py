"""Tests for HealthRiskAssessmentButton handler."""

from unittest.mock import MagicMock, call, patch

import pytest

from health_risk_assessment.protocols.health_risk_assessment import (
    HealthRiskAssessmentButton,
)


class TestHealthRiskAssessmentButtonConfiguration:
    """Tests for button configuration."""

    def test_button_title_is_correct(self) -> None:
        """Test that button title matches specification."""
        assert HealthRiskAssessmentButton.BUTTON_TITLE == "Health Risk Assessment"

    def test_button_key_is_set(self) -> None:
        """Test that button key is set."""
        assert HealthRiskAssessmentButton.BUTTON_KEY == "COMPLETE_HRA"

    def test_button_location_is_note_header(self) -> None:
        """Test that button is configured for note header."""
        from canvas_sdk.handlers.action_button import ActionButton

        assert (
            HealthRiskAssessmentButton.BUTTON_LOCATION
            == ActionButton.ButtonLocation.NOTE_HEADER
        )

    def test_questionnaire_code_is_configured(self) -> None:
        """Test that questionnaire code constants are set."""
        assert HealthRiskAssessmentButton.QUESTIONNAIRE_CODE == "HRA_AWV"
        assert HealthRiskAssessmentButton.QUESTIONNAIRE_CODE_SYSTEM == "INTERNAL"


class TestHealthRiskAssessmentButtonVisibility:
    """Tests for button visibility logic."""

    def test_visible_returns_false_when_no_note_id_in_context(self) -> None:
        """Test that button is hidden when note_id is missing from context."""
        mock_event = MagicMock()
        mock_event.context = {}

        with patch.object(
            HealthRiskAssessmentButton, "context", new_callable=lambda: property(lambda self: {})
        ):
            handler = HealthRiskAssessmentButton(event=mock_event)
            result = handler.visible()
            assert result is False

    def test_visible_returns_false_when_note_state_event_not_found(self) -> None:
        """Test that button is hidden when note state event doesn't exist."""
        mock_event = MagicMock()

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": 123}),
        ):
            with patch(
                "health_risk_assessment.protocols.health_risk_assessment.CurrentNoteStateEvent.objects"
            ) as mock_state_objects:
                from canvas_sdk.v1.data.note import CurrentNoteStateEvent
                mock_state_objects.get.side_effect = CurrentNoteStateEvent.DoesNotExist

                handler = HealthRiskAssessmentButton(event=mock_event)
                result = handler.visible()

                assert result is False

    def test_visible_returns_false_when_note_is_locked(self) -> None:
        """Test that button is hidden when note is in locked state."""
        mock_event = MagicMock()

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": 123}),
        ):
            with patch(
                "health_risk_assessment.protocols.health_risk_assessment.CurrentNoteStateEvent.objects"
            ) as mock_state_objects:
                # Note state 'LKD' = Locked, which is not in ALLOWED_NOTE_STATES
                mock_state_event = MagicMock()
                mock_state_event.state = "LKD"
                mock_state_objects.get.return_value = mock_state_event

                handler = HealthRiskAssessmentButton(event=mock_event)
                result = handler.visible()

                mock_state_objects.get.assert_called_once_with(note__dbid=123)
                assert result is False

    def test_visible_returns_true_when_note_unlocked_and_no_existing_hra(
        self, mock_note: MagicMock
    ) -> None:
        """Test that button is visible when note is unlocked and no HRA exists."""
        mock_event = MagicMock()

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": 123}),
        ):
            with patch(
                "health_risk_assessment.protocols.health_risk_assessment.CurrentNoteStateEvent.objects"
            ) as mock_state_objects:
                with patch(
                    "health_risk_assessment.protocols.health_risk_assessment.Note.objects"
                ) as mock_note_objects:
                    # Note state 'NEW' is in ALLOWED_NOTE_STATES
                    mock_state_event = MagicMock()
                    mock_state_event.state = "NEW"
                    mock_state_objects.get.return_value = mock_state_event

                    # Mock no custom commands and no questionnaire commands
                    mock_custom_commands = MagicMock()
                    mock_custom_commands.exists.return_value = False

                    def filter_side_effect(schema_key=None):
                        if schema_key == "healthRiskAssessmentSummary":
                            return mock_custom_commands
                        return []  # No questionnaire commands

                    mock_note.commands.filter.side_effect = filter_side_effect
                    mock_note_objects.get.return_value = mock_note

                    handler = HealthRiskAssessmentButton(event=mock_event)
                    result = handler.visible()

                    # Verify CurrentNoteStateEvent.objects.get was called
                    mock_state_objects.get.assert_called_once_with(note__dbid=123)

                    # Verify Note.objects.get was called
                    mock_note_objects.get.assert_called_once_with(dbid=123)

                    assert result is True

    def test_visible_returns_false_when_hra_exists_by_text_name(
        self, mock_note: MagicMock
    ) -> None:
        """Test that button is hidden when HRA questionnaire exists (detected by text name)."""
        mock_event = MagicMock()

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": 123}),
        ):
            with patch(
                "health_risk_assessment.protocols.health_risk_assessment.CurrentNoteStateEvent.objects"
            ) as mock_state_objects:
                with patch(
                    "health_risk_assessment.protocols.health_risk_assessment.Note.objects"
                ) as mock_note_objects:
                    # Note state 'NEW' is in ALLOWED_NOTE_STATES
                    mock_state_event = MagicMock()
                    mock_state_event.state = "NEW"
                    mock_state_objects.get.return_value = mock_state_event

                    # Mock no custom command but existing HRA questionnaire command
                    mock_custom_commands = MagicMock()
                    mock_custom_commands.exists.return_value = False

                    mock_command = MagicMock()
                    mock_command.data = {
                        "questionnaire": {
                            "text": "Health Risk Assessment",
                            "extra": {},
                        }
                    }

                    def filter_side_effect(schema_key=None):
                        if schema_key == "healthRiskAssessmentSummary":
                            return mock_custom_commands
                        return [mock_command]  # Questionnaire commands

                    mock_note.commands.filter.side_effect = filter_side_effect
                    mock_note_objects.get.return_value = mock_note

                    handler = HealthRiskAssessmentButton(event=mock_event)
                    result = handler.visible()

                    assert result is False

    def test_visible_returns_false_when_hra_exists_by_extra_name(
        self, mock_note: MagicMock
    ) -> None:
        """Test that button is hidden when HRA questionnaire exists (detected by extra name)."""
        mock_event = MagicMock()

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": 123}),
        ):
            with patch(
                "health_risk_assessment.protocols.health_risk_assessment.CurrentNoteStateEvent.objects"
            ) as mock_state_objects:
                with patch(
                    "health_risk_assessment.protocols.health_risk_assessment.Note.objects"
                ) as mock_note_objects:
                    # Note state 'NEW' is in ALLOWED_NOTE_STATES
                    mock_state_event = MagicMock()
                    mock_state_event.state = "NEW"
                    mock_state_objects.get.return_value = mock_state_event

                    # Mock no custom command but existing HRA questionnaire command
                    mock_custom_commands = MagicMock()
                    mock_custom_commands.exists.return_value = False

                    mock_command = MagicMock()
                    mock_command.data = {
                        "questionnaire": {
                            "text": "Some Other Questionnaire",
                            "extra": {"name": "Health Risk Assessment"},
                        }
                    }

                    def filter_side_effect(schema_key=None):
                        if schema_key == "healthRiskAssessmentSummary":
                            return mock_custom_commands
                        return [mock_command]  # Questionnaire commands

                    mock_note.commands.filter.side_effect = filter_side_effect
                    mock_note_objects.get.return_value = mock_note

                    handler = HealthRiskAssessmentButton(event=mock_event)
                    result = handler.visible()

                    assert result is False

    def test_visible_returns_false_when_custom_command_exists(
        self, mock_note: MagicMock
    ) -> None:
        """Test that button is hidden when HRA custom command exists."""
        mock_event = MagicMock()

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": 123}),
        ):
            with patch(
                "health_risk_assessment.protocols.health_risk_assessment.CurrentNoteStateEvent.objects"
            ) as mock_state_objects:
                with patch(
                    "health_risk_assessment.protocols.health_risk_assessment.Note.objects"
                ) as mock_note_objects:
                    # Note state 'NEW' is in ALLOWED_NOTE_STATES
                    mock_state_event = MagicMock()
                    mock_state_event.state = "NEW"
                    mock_state_objects.get.return_value = mock_state_event

                    # Mock existing custom command
                    mock_custom_commands = MagicMock()
                    mock_custom_commands.exists.return_value = True

                    # Configure filter to return custom commands for schema_key check
                    def filter_side_effect(schema_key=None):
                        if schema_key == "healthRiskAssessmentSummary":
                            return mock_custom_commands
                        return []

                    mock_note.commands.filter.side_effect = filter_side_effect
                    mock_note_objects.get.return_value = mock_note

                    handler = HealthRiskAssessmentButton(event=mock_event)
                    result = handler.visible()

                    assert result is False


class TestHealthRiskAssessmentButtonHandle:
    """Tests for button click handling."""

    def test_handle_returns_launch_modal_effect(
        self, mock_questionnaire: MagicMock
    ) -> None:
        """Test that handle() returns a LaunchModalEffect."""
        mock_event = MagicMock()
        mock_event.context = {"note_id": "test-note-123"}
        mock_event.target = "test-patient-456"

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": "test-note-123"}),
        ):
            with patch.object(
                HealthRiskAssessmentButton,
                "target",
                new_callable=lambda: property(lambda self: "test-patient-456"),
            ):
                with patch(
                    "health_risk_assessment.protocols.health_risk_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.health_risk_assessment.render_to_string"
                    ) as mock_render:
                        with patch(
                            "health_risk_assessment.protocols.health_risk_assessment.LaunchModalEffect"
                        ) as mock_modal_class:
                            mock_q_objects.filter.return_value.first.return_value = (
                                mock_questionnaire
                            )
                            mock_render.return_value = "<html>test</html>"
                            mock_modal_instance = MagicMock()
                            mock_modal_class.return_value = mock_modal_instance
                            mock_modal_instance.apply.return_value = MagicMock()

                            handler = HealthRiskAssessmentButton(event=mock_event)
                            effects = handler.handle()

                            # Verify Questionnaire.objects.filter was called
                            mock_q_objects.filter.assert_called_once_with(
                                code="HRA_AWV", code_system="INTERNAL", status="AC"
                            )

                            # Verify render_to_string was called with correct template
                            mock_render.assert_called_once()
                            call_args = mock_render.call_args
                            assert call_args[0][0] == "templates/assessment_form.html"
                            context = call_args[0][1]
                            assert context["note_id"] == "test-note-123"
                            assert context["patient_id"] == "test-patient-456"
                            assert context["questionnaire_id"] == str(mock_questionnaire.id)

                            # Verify effects returned
                            assert len(effects) == 1

    def test_handle_with_no_questionnaire_found(self) -> None:
        """Test handle() when questionnaire is not found in database."""
        mock_event = MagicMock()
        mock_event.context = {"note_id": "test-note-123"}
        mock_event.target = "test-patient-456"

        with patch.object(
            HealthRiskAssessmentButton,
            "context",
            new_callable=lambda: property(lambda self: {"note_id": "test-note-123"}),
        ):
            with patch.object(
                HealthRiskAssessmentButton,
                "target",
                new_callable=lambda: property(lambda self: "test-patient-456"),
            ):
                with patch(
                    "health_risk_assessment.protocols.health_risk_assessment.Questionnaire.objects"
                ) as mock_q_objects:
                    with patch(
                        "health_risk_assessment.protocols.health_risk_assessment.render_to_string"
                    ) as mock_render:
                        with patch(
                            "health_risk_assessment.protocols.health_risk_assessment.LaunchModalEffect"
                        ) as mock_modal_class:
                            mock_q_objects.filter.return_value.first.return_value = None
                            mock_render.return_value = "<html>test</html>"
                            mock_modal_instance = MagicMock()
                            mock_modal_class.return_value = mock_modal_instance
                            mock_modal_instance.apply.return_value = MagicMock()

                            handler = HealthRiskAssessmentButton(event=mock_event)
                            effects = handler.handle()

                            # Verify questionnaire_id is empty string when not found
                            call_args = mock_render.call_args
                            context = call_args[0][1]
                            assert context["questionnaire_id"] == ""

                            # Still returns a modal
                            assert len(effects) == 1
