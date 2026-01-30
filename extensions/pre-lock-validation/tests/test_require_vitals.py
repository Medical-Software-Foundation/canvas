# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# For more information on testing Canvas plugins, see: https://docs.canvasmedical.com/sdk/testing-utils/

from unittest.mock import Mock, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType

from pre_lock_validation.handlers.require_vitals import RequireVitalsToLockHandler


def test_vitals_handler_event_configuration() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE) == RequireVitalsToLockHandler.RESPONDS_TO


def test_vitals_handler_allows_non_lock_states() -> None:
    """Test that the handler allows state changes that are not LKD."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "NEW",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    handler = RequireVitalsToLockHandler(event=mock_event)
    effects = handler.compute()

    assert len(effects) == 0


@patch("pre_lock_validation.handlers.require_vitals.Command")
def test_vitals_handler_blocks_lock_without_vitals(mock_command) -> None:
    """Test that the handler blocks locking when no committed vitals exist."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "LKD",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    # Mock Command.objects.filter to return empty queryset
    mock_queryset = Mock()
    mock_queryset.exists.return_value = False
    mock_command.objects.filter.return_value = mock_queryset

    handler = RequireVitalsToLockHandler(event=mock_event)
    effects = handler.compute()

    # Should return one validation error effect
    assert len(effects) == 1
    assert effects[0].type == EffectType.EVENT_VALIDATION_ERROR

    # Verify the command filter was called with correct parameters
    mock_command.objects.filter.assert_called_once_with(
        note__id="test-note-id",
        schema_key="vitals",
        state="committed"
    )


@patch("pre_lock_validation.handlers.require_vitals.Command")
def test_vitals_handler_allows_lock_with_vitals(mock_command) -> None:
    """Test that the handler allows locking when committed vitals exist."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
    mock_event.context = {
        "state": "LKD",
        "note_id": "test-note-id",
        "patient_id": "test-patient-id",
    }

    # Mock Command.objects.filter to return a queryset with vitals
    mock_queryset = Mock()
    mock_queryset.exists.return_value = True
    mock_command.objects.filter.return_value = mock_queryset

    handler = RequireVitalsToLockHandler(event=mock_event)
    effects = handler.compute()

    # Should return no effects (allow the lock)
    assert len(effects) == 0

    # Verify the command filter was called with correct parameters
    mock_command.objects.filter.assert_called_once_with(
        note__id="test-note-id",
        schema_key="vitals",
        state="committed"
    )
