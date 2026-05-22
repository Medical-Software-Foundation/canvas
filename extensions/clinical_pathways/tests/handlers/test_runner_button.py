"""Tests for clinical_pathways.handlers.runner_button."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note

from clinical_pathways.handlers.runner_button import PathwayRunnerButton


def _make_button() -> PathwayRunnerButton:
    button = PathwayRunnerButton()
    button.context = {}
    button.target = ""
    return button


class TestVisible:
    def test_returns_false_when_no_note_id(self) -> None:
        button = _make_button()
        button.context = {}
        assert button.visible() is False

    def test_returns_false_when_state_event_missing(self) -> None:
        button = _make_button()
        button.context = {"note_id": 99}
        with patch.object(CurrentNoteStateEvent, "objects") as mock_objects:
            mock_objects.get.side_effect = CurrentNoteStateEvent.DoesNotExist()
            assert button.visible() is False

    def test_returns_true_for_editable_state(self) -> None:
        button = _make_button()
        button.context = {"note_id": 7}
        state = MagicMock()
        state.state = "NEW"
        with patch.object(CurrentNoteStateEvent, "objects") as mock_objects:
            mock_objects.get.return_value = state
            assert button.visible() is True

    def test_returns_false_for_locked_state(self) -> None:
        button = _make_button()
        button.context = {"note_id": 7}
        state = MagicMock()
        state.state = "LKD"
        with patch.object(CurrentNoteStateEvent, "objects") as mock_objects:
            mock_objects.get.return_value = state
            assert button.visible() is False


class TestHandle:
    def test_returns_empty_when_note_not_found(self) -> None:
        button = _make_button()
        button.context = {"note_id": 123}
        button.target = "patient-1"
        with patch.object(Note, "objects") as mock_objects:
            mock_objects.get.side_effect = Note.DoesNotExist()
            assert button.handle() == []

    def test_emits_launch_modal_effect_to_right_chart_pane(
        self, stub_effect_type: type
    ) -> None:
        button = _make_button()
        button.context = {"note_id": 5}
        button.target = "patient-99"

        note = MagicMock()
        note.id = "note-uuid-abc"
        with patch.object(Note, "objects") as mock_objects:
            mock_objects.get.return_value = note
            effects = button.handle()

        assert len(effects) == 1
        effect = effects[0]
        assert isinstance(effect, stub_effect_type)
        assert effect.tag == "LaunchModalEffect"
        assert effect.payload["target"] == "RIGHT_CHART_PANE"
        assert effect.payload["title"] == "Pick a clinical pathway"
        assert "note_uuid=note-uuid-abc" in effect.payload["url"]
        assert "patient_id=patient-99" in effect.payload["url"]

    def test_handle_defaults_patient_id_when_target_missing(self) -> None:
        button = _make_button()
        button.context = {"note_id": 5}
        button.target = None

        note = MagicMock()
        note.id = "note-uuid-xyz"
        with patch.object(Note, "objects") as mock_objects:
            mock_objects.get.return_value = note
            effects = button.handle()

        assert "patient_id=" in effects[0].payload["url"]
