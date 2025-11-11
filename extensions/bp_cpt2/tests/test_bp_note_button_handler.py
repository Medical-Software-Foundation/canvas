# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch, PropertyMock

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data import Note
from canvas_sdk.v1.data.note import NoteStateChangeEvent, NoteStates

from bp_cpt2.handlers.bp_note_button_handler import BloodPressureNoteButtonHandler
from bp_cpt2 import bp_claim_coder


def test_button_visible_when_secret_true_and_note_editable() -> None:
    """
    Test that button is visible when SHOW_BUTTON_FOR_MANUAL_TRIGGER is true
    and note is in an editable state.
    """
    # Create test patient and note
    patient = PatientFactory.create()
    note = Note.objects.create(
        patient=patient,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create note state change event - note is in NEW (editable) state
    NoteStateChangeEvent.objects.create(
        note_id=note.dbid,
        state=NoteStates.NEW,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create mock event with context
    mock_event = Mock()
    mock_event.context = {'note_id': note.dbid}

    # Create handler instance with secret enabled
    handler = BloodPressureNoteButtonHandler(
        event=mock_event,
        secrets={'SHOW_BUTTON_FOR_MANUAL_TRIGGER': 'true'}
    )

    # Button should be visible
    assert handler.visible() is True


def test_button_hidden_when_secret_false() -> None:
    """
    Test that button is hidden when SHOW_BUTTON_FOR_MANUAL_TRIGGER is false,
    regardless of note state.
    """
    # Create test patient and note
    patient = PatientFactory.create()
    note = Note.objects.create(
        patient=patient,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create note state change event
    NoteStateChangeEvent.objects.create(
        note_id=note.dbid,
        state=NoteStates.NEW,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create mock context
    mock_event = Mock()
    mock_event.context = {'note_id': note.dbid}

    # Create handler instance with secret disabled
    handler = BloodPressureNoteButtonHandler(
        event=mock_event,
        secrets={'SHOW_BUTTON_FOR_MANUAL_TRIGGER': 'false'}
    )

    # Button should be hidden
    assert handler.visible() is False


def test_button_hidden_when_note_locked() -> None:
    """
    Test that button is hidden when note is in LOCKED state (not editable).
    """
    # Create test patient and note
    patient = PatientFactory.create()
    note = Note.objects.create(
        patient=patient,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create note state change event - note is LOCKED
    NoteStateChangeEvent.objects.create(
        note_id=note.dbid,
        state=NoteStates.LOCKED,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create mock context
    mock_event = Mock()
    mock_event.context = {'note_id': note.dbid}

    # Create handler instance with secret enabled
    handler = BloodPressureNoteButtonHandler(
        event=mock_event,
        secrets={'SHOW_BUTTON_FOR_MANUAL_TRIGGER': 'true'}
    )

    # Button should be hidden because note is locked
    assert handler.visible() is False


def test_button_visible_for_various_editable_states() -> None:
    """
    Test that button is visible for all editable note states.
    """
    patient = PatientFactory.create()

    editable_states = [
        NoteStates.NEW,
        NoteStates.PUSHED,
        NoteStates.UNLOCKED,
        NoteStates.RESTORED,
        NoteStates.UNDELETED,
        NoteStates.CONVERTED,
    ]

    for state in editable_states:
        # Create a note
        note = Note.objects.create(
            patient=patient,
            created=datetime.now(timezone.utc),
            modified=datetime.now(timezone.utc)
        )

        # Create note state change event
        NoteStateChangeEvent.objects.create(
            note_id=note.dbid,
            state=state,
            created=datetime.now(timezone.utc),
            modified=datetime.now(timezone.utc)
        )

        # Create mock context
        mock_event = Mock()
        mock_event.context = {'note_id': note.dbid}

        # Create handler instance
        handler = BloodPressureNoteButtonHandler(
            event=mock_event,
            secrets={'SHOW_BUTTON_FOR_MANUAL_TRIGGER': 'true'}
        )

        # Button should be visible for this editable state
        assert handler.visible() is True, f"Button should be visible for state {state}"


def test_handle_returns_empty_when_note_not_found() -> None:
    """
    Test that handle() returns empty list when note doesn't exist.
    """
    # Create mock context with non-existent note_id
    mock_event = Mock()
    mock_event.context = {'note_id': 999999}

    # Create handler
    handler = BloodPressureNoteButtonHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    # Execute handle
    effects = handler.handle()

    # Should return empty list
    assert effects == []


def test_handle_skips_non_billable_notes() -> None:
    """
    Test that handle() skips processing for non-billable notes.
    """
    # Create test patient and note
    patient = PatientFactory.create()
    note = Note.objects.create(
        patient=patient,
        created=datetime.now(timezone.utc),
        modified=datetime.now(timezone.utc)
    )

    # Create mock context
    mock_event = Mock()
    mock_event.context = {'note_id': note.dbid}

    # Mock note_type_version as non-billable
    mock_note_type = Mock()
    mock_note_type.is_billable = False

    # Create handler
    handler = BloodPressureNoteButtonHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    with patch.object(type(note), 'note_type_version', new_callable=PropertyMock, return_value=mock_note_type):
        # Execute handle
        effects = handler.handle()

        # Should return empty list
        assert effects == []


def test_handle_returns_empty_when_no_note_id_in_context() -> None:
    """
    Test that handle() returns empty list when note_id is missing from context.
    Covers lines 54-55.
    """
    # Create mock event with empty context (no note_id)
    mock_event = Mock()
    mock_event.context = {}

    # Create handler
    handler = BloodPressureNoteButtonHandler(
        event=mock_event,
        secrets={'OPENAI_API_KEY': 'test-key'}
    )

    # Execute handle
    effects = handler.handle()

    # Should return empty list
    assert effects == []


