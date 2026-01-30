"""Tests for NoStagedCommandsToLockHandler."""

from unittest.mock import patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from pre_lock_validation.handlers.no_staged_commands import NoStagedCommandsToLockHandler
from tests.conftest import create_mock_command


def test_handler_responds_to_pre_create_event() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert NoStagedCommandsToLockHandler.RESPONDS_TO == EventType.Name(
        EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    )


def test_allows_non_lock_states(mock_event) -> None:
    """Test that the handler allows state changes that are not LKD."""
    handler = NoStagedCommandsToLockHandler(event=mock_event(state="NEW"))
    effects = handler.compute()
    assert len(effects) == 0


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_blocks_lock_with_staged_commands(mock_command, mock_event, mock_command_chain) -> None:
    """Test that the handler blocks locking when staged commands exist."""
    commands = [
        create_mock_command("prescribe"),
        create_mock_command("diagnose"),
        create_mock_command("prescribe"),  # Duplicate to test deduplication
    ]
    mock_exclude_result = mock_command_chain(mock_command, commands)

    handler = NoStagedCommandsToLockHandler(event=mock_event(state="LKD"))
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR
    mock_command.objects.exclude.assert_called_once_with(schema_key='reasonForVisit')
    mock_exclude_result.filter.assert_called_once_with(
        note__id="test-note-id",
        state="staged"
    )


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_allows_lock_without_staged_commands(mock_command, mock_event, mock_command_chain) -> None:
    """Test that the handler allows locking when no staged commands exist."""
    mock_exclude_result = mock_command_chain(mock_command, commands=[])

    handler = NoStagedCommandsToLockHandler(event=mock_event(state="LKD"))
    effects = handler.compute()

    assert len(effects) == 0
    mock_command.objects.exclude.assert_called_once_with(schema_key='reasonForVisit')
    mock_exclude_result.filter.assert_called_once_with(
        note__id="test-note-id",
        state="staged"
    )


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_error_message_contains_count_and_types(mock_command, mock_event, mock_command_chain) -> None:
    """Test that the error message includes the count and schema_keys of staged commands."""
    commands = [
        create_mock_command("prescribe"),
        create_mock_command("vitals"),
    ]
    mock_command_chain(mock_command, commands)

    handler = NoStagedCommandsToLockHandler(event=mock_event(state="LKD"))
    effects = handler.compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_excludes_reason_for_visit(mock_command, mock_event, mock_command_chain) -> None:
    """Test that reasonForVisit commands are excluded from validation."""
    mock_command_chain(mock_command, commands=[])

    handler = NoStagedCommandsToLockHandler(event=mock_event(state="LKD"))
    effects = handler.compute()

    assert len(effects) == 0
    mock_command.objects.exclude.assert_called_once_with(schema_key='reasonForVisit')
