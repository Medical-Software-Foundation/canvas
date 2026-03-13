# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.
# If you want to modify which files are used for testing, check the [tool.pytest.ini_options] section in pyproject.toml.
# For more information on testing Canvas plugins, see: https://docs.canvasmedical.com/sdk/testing-utils/

from unittest.mock import Mock

from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.discount import Discount

from claim_pdf_generator.handlers.event_handlers import NewOfficeVisitNoteHandler


# Test the handler's compute method with mocked event data
def test_handler_responds_to_new_office_visit_note() -> None:
    """Test that the handler originates commands for a new office visit note."""
    # Create a mock event with the expected structure
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_CREATED
    mock_event.context = {
        "state": "NEW",
        "note_id": 123,
        "patient_id": 456,
    }

    # Mock the note instance
    mock_note = Mock()
    mock_note.uuid = "test-note-uuid-123"
    mock_note.note_type_version.name = "OFFICE VISIT"
    mock_event.target.instance = mock_note

    # Instantiate the handler with the mock event
    handler = NewOfficeVisitNoteHandler(event=mock_event)

    # Call compute and get the effects
    effects = handler.compute()

    # Assert that two effects were returned (vitals and goal)
    assert len(effects) == 2

    # Assert both effects have the correct type
    assert all(effect.type == EffectType.ORIGINATE_COMMAND for effect in effects)

    # Verify that the effects contain the correct note_uuid in their payloads
    for effect in effects:
        assert "test-note-uuid-123" in effect.payload


def test_handler_skips_non_new_notes() -> None:
    """Test that the handler skips notes that are not in NEW state."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_CREATED
    mock_event.context = {
        "state": "SIGNED",
        "note_id": 123,
        "patient_id": 456,
    }

    # Mock the note instance
    mock_note = Mock()
    mock_note.uuid = "test-note-uuid-123"
    mock_note.note_type_version.name = "OFFICE VISIT"
    mock_event.target.instance = mock_note

    handler = NewOfficeVisitNoteHandler(event=mock_event)
    effects = handler.compute()

    # Assert that no effects were returned
    assert len(effects) == 0


def test_handler_skips_non_office_visit_notes() -> None:
    """Test that the handler skips notes that are not office visits."""
    mock_event = Mock()
    mock_event.type = EventType.NOTE_STATE_CHANGE_EVENT_CREATED
    mock_event.context = {
        "state": "NEW",
        "note_id": 123,
        "patient_id": 456,
    }

    # Mock the note instance
    mock_note = Mock()
    mock_note.uuid = "test-note-uuid-123"
    mock_note.note_type_version.name = "PROGRESS NOTE"
    mock_event.target.instance = mock_note

    handler = NewOfficeVisitNoteHandler(event=mock_event)
    effects = handler.compute()

    # Assert that no effects were returned
    assert len(effects) == 0


# Test that the handler class has the correct event type configured
def test_handler_event_configuration() -> None:
    """Test that the handler is configured to respond to the correct event type."""
    assert EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED) == NewOfficeVisitNoteHandler.RESPONDS_TO


# Example: You can use a factory to create a patient instance for testing purposes.
def test_factory_example() -> None:
    """Test that a patient can be created using the PatientFactory."""
    patient = PatientFactory.create()
    assert patient.id is not None


# Example: If a factory is not available, you can create an instance manually with the data model directly.
def test_model_example() -> None:
    """Test that a Discount instance can be created."""
    Discount.objects.create(name="10%", adjustment_group="30", adjustment_code="CO", discount=0.10)
    assert Discount.objects.first().pk is not None
