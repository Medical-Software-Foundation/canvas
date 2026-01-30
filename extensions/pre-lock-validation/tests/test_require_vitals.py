"""Tests for RequireVitalsToLockHandler."""

from unittest.mock import patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from pre_lock_validation.handlers.require_vitals import RequireVitalsToLockHandler


def test_handler_responds_to_pre_create_event() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert RequireVitalsToLockHandler.RESPONDS_TO == EventType.Name(
        EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    )


def test_allows_non_lock_states(mock_event) -> None:
    """Test that the handler allows state changes that are not LKD."""
    handler = RequireVitalsToLockHandler(event=mock_event(state="NEW"))
    effects = handler.compute()
    assert len(effects) == 0


@patch("pre_lock_validation.handlers.require_vitals.Command")
def test_blocks_lock_without_vitals(mock_command, mock_event, mock_command_filter) -> None:
    """Test that the handler blocks locking when no committed vitals exist."""
    mock_command_filter(mock_command, exists=False)

    handler = RequireVitalsToLockHandler(event=mock_event(state="LKD"))
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR
    mock_command.objects.filter.assert_called_once_with(
        note__id="test-note-id",
        schema_key="vitals",
        state="committed"
    )


@patch("pre_lock_validation.handlers.require_vitals.Command")
def test_allows_lock_with_vitals(mock_command, mock_event, mock_command_filter) -> None:
    """Test that the handler allows locking when committed vitals exist."""
    mock_command_filter(mock_command, exists=True)

    handler = RequireVitalsToLockHandler(event=mock_event(state="LKD"))
    effects = handler.compute()

    assert len(effects) == 0
    mock_command.objects.filter.assert_called_once_with(
        note__id="test-note-id",
        schema_key="vitals",
        state="committed"
    )
