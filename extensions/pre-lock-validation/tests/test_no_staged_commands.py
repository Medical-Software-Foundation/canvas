# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# For more information on testing Canvas plugins, see: https://docs.canvasmedical.com/sdk/testing-utils/

from unittest.mock import Mock, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from pre_lock_validation.handlers.no_staged_commands import NoStagedCommandsToLockHandler


def test_staged_handler_event_configuration() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE) == NoStagedCommandsToLockHandler.RESPONDS_TO


def test_staged_handler_allows_non_lock_states() -> None:
    """Test that the handler allows state changes that are not LKD."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "NEW",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    handler = NoStagedCommandsToLockHandler(event=mock_event)
    effects = handler.compute()

    assert len(effects) == 0


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_staged_handler_blocks_lock_with_staged_commands(mock_command) -> None:
    """Test that the handler blocks locking when staged commands exist."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "LKD",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    # Create mock staged commands with schema_keys
    mock_cmd1 = Mock()
    mock_cmd1.schema_key = "prescribe"
    mock_cmd2 = Mock()
    mock_cmd2.schema_key = "diagnose"
    mock_cmd3 = Mock()
    mock_cmd3.schema_key = "prescribe"  # Duplicate to test deduplication

    # Mock the chained query: Command.objects.exclude(...).filter(...)
    mock_filter_result = Mock()
    mock_filter_result.__iter__ = Mock(return_value=iter([mock_cmd1, mock_cmd2, mock_cmd3]))

    mock_exclude_result = Mock()
    mock_exclude_result.filter.return_value = mock_filter_result

    mock_command.objects.exclude.return_value = mock_exclude_result

    handler = NoStagedCommandsToLockHandler(event=mock_event)
    effects = handler.compute()

    # Should return one validation error effect
    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR

    # Verify the query chain was called correctly
    mock_command.objects.exclude.assert_called_once_with(schema_key='reasonForVisit')
    mock_exclude_result.filter.assert_called_once_with(
        note__id="test-note-id",
        state="staged"
    )


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_staged_handler_allows_lock_without_staged_commands(mock_command) -> None:
    """Test that the handler allows locking when no staged commands exist."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "LKD",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    # Mock the chained query to return empty list
    mock_filter_result = Mock()
    mock_filter_result.__iter__ = Mock(return_value=iter([]))

    mock_exclude_result = Mock()
    mock_exclude_result.filter.return_value = mock_filter_result

    mock_command.objects.exclude.return_value = mock_exclude_result

    handler = NoStagedCommandsToLockHandler(event=mock_event)
    effects = handler.compute()

    # Should return no effects (allow the lock)
    assert len(effects) == 0

    # Verify the query chain was called correctly
    mock_command.objects.exclude.assert_called_once_with(schema_key='reasonForVisit')
    mock_exclude_result.filter.assert_called_once_with(
        note__id="test-note-id",
        state="staged"
    )


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_staged_handler_error_message_contains_count_and_types(mock_command) -> None:
    """Test that the error message includes the count and schema_keys of staged commands."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "LKD",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    # Create mock staged commands
    mock_cmd1 = Mock()
    mock_cmd1.schema_key = "prescribe"
    mock_cmd2 = Mock()
    mock_cmd2.schema_key = "vitals"

    # Mock the chained query
    mock_filter_result = Mock()
    mock_filter_result.__iter__ = Mock(return_value=iter([mock_cmd1, mock_cmd2]))

    mock_exclude_result = Mock()
    mock_exclude_result.filter.return_value = mock_filter_result

    mock_command.objects.exclude.return_value = mock_exclude_result

    handler = NoStagedCommandsToLockHandler(event=mock_event)
    effects = handler.compute()

    # Check error message contains count and schema_keys
    assert len(effects) == 1
    effect = effects[0]
    assert effect.type == EffectType.EVENT_VALIDATION_ERROR


@patch("pre_lock_validation.handlers.no_staged_commands.Command")
def test_staged_handler_excludes_reason_for_visit(mock_command) -> None:
    """Test that reasonForVisit commands are excluded from validation."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "LKD",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    # Mock the chained query to return empty (simulating only reasonForVisit was staged)
    mock_filter_result = Mock()
    mock_filter_result.__iter__ = Mock(return_value=iter([]))

    mock_exclude_result = Mock()
    mock_exclude_result.filter.return_value = mock_filter_result

    mock_command.objects.exclude.return_value = mock_exclude_result

    handler = NoStagedCommandsToLockHandler(event=mock_event)
    effects = handler.compute()

    # Should allow lock since reasonForVisit is excluded
    assert len(effects) == 0

    # Verify exclude was called with reasonForVisit
    mock_command.objects.exclude.assert_called_once_with(schema_key='reasonForVisit')
