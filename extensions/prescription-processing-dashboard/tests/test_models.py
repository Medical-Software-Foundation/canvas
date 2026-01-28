# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.
# If you want to modify which files are used for testing, check the [tool.pytest.ini_options] section in pyproject.toml.
# For more information on testing Canvas plugins, see: https://docs.canvasmedical.com/sdk/testing-utils/

from unittest.mock import Mock

import pytest
from canvas_sdk.effects import EffectType
from canvas_sdk.events import EventType
from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.discount import Discount

from prescription_processing_dashboard.protocols.my_protocol import Protocol


# Test the protocol's compute method with mocked event data
def test_protocol_responds_to_assess_command() -> None:
    """Test that the protocol responds correctly to ASSESS_COMMAND__CONDITION_SELECTED events."""
    # Create a mock event with the expected structure
    mock_event = Mock()
    mock_event.type = EventType.ASSESS_COMMAND__CONDITION_SELECTED
    mock_event.context = {
        "note": {
            "uuid": "test-note-uuid-123",
        }
    }

    # Instantiate the protocol with the mock event
    protocol = Protocol(event=mock_event)

    # Call compute and get the effects
    effects = protocol.compute()

    # Assert that effects were returned
    assert len(effects) == 1

    # Assert the effect has the correct type
    assert effects[0].type == EffectType.LOG

    # Assert the effect contains expected data
    assert "test-note-uuid-123" in effects[0].payload
    assert protocol.NARRATIVE_STRING in effects[0].payload


# Test that the protocol class has the correct event type configured
def test_protocol_event_configuration() -> None:
    """Test that the protocol is configured to respond to the correct event type."""
    assert EventType.Name(EventType.ASSESS_COMMAND__CONDITION_SELECTED) == Protocol.RESPONDS_TO


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
