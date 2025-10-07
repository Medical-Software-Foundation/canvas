# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from unittest.mock import Mock

from canvas_sdk.events import EventType

from bp_cpt2.handlers.bp_note_state_handler import BloodPressureNoteStateHandler


def test_handler_logs_not_implemented() -> None:
    """
    Test that BloodPressureNoteStateHandler logs that it's not implemented
    and returns empty effects for locked notes.
    """
    # Create mock event for note state change to locked
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_CREATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'LKD',  # Locked state
        'note_id': str(uuid.uuid4())
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify no effects are created (handler is not implemented)
    assert len(effects) == 0, "Expected no billing codes from note state handler (not implemented)"


def test_skips_non_locked_states() -> None:
    """
    Test that BloodPressureNoteStateHandler skips processing for
    note states other than 'LKD' (locked).
    """
    # Create mock event for note state change to NEW (not locked)
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_CREATED
    mock_target = Mock()
    mock_target.id = str(uuid.uuid4())
    mock_event.target = mock_target
    mock_event.context = {
        'state': 'NEW',  # New state, not locked
        'note_id': str(uuid.uuid4())
    }

    # Create handler instance
    handler = BloodPressureNoteStateHandler(
        event=mock_event,
        secrets={}
    )

    # Execute compute
    effects = handler.compute()

    # Verify that no effects are created for non-locked states
    assert len(effects) == 0, "Expected no billing codes for non-locked note state"
