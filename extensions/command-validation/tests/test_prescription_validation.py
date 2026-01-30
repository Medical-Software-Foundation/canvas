"""Tests for RequireDaysSupplyHandler."""

from unittest.mock import Mock, patch

from canvas_sdk.events import EventType

from command_validation.handlers.prescription_validation import RequireDaysSupplyHandler


def test_handler_responds_to_prescribe_events() -> None:
    """Test that the handler is configured to respond to prescription events."""
    assert EventType.Name(EventType.PRESCRIBE_COMMAND__POST_VALIDATION) in RequireDaysSupplyHandler.RESPONDS_TO
    assert EventType.Name(EventType.REFILL_COMMAND__POST_VALIDATION) in RequireDaysSupplyHandler.RESPONDS_TO
    assert EventType.Name(EventType.ADJUST_PRESCRIPTION_COMMAND__POST_VALIDATION) in RequireDaysSupplyHandler.RESPONDS_TO


@patch("command_validation.handlers.prescription_validation.Command")
def test_blocks_commit_with_missing_days_supply(mock_command) -> None:
    """Test that the handler blocks commit when days_supply is missing."""
    event = Mock()
    event.target.id = "test-command-id"

    command = Mock()
    command.data = {"sig": "Take one daily", "quantity_to_dispense": 30}
    mock_command.objects.get.return_value = command

    handler = RequireDaysSupplyHandler(event=event)
    effects = handler.compute()

    assert len(effects) == 1


@patch("command_validation.handlers.prescription_validation.Command")
def test_blocks_commit_with_zero_days_supply(mock_command) -> None:
    """Test that the handler blocks commit when days_supply is 0."""
    event = Mock()
    event.target.id = "test-command-id"

    command = Mock()
    command.data = {"days_supply": 0, "sig": "Take one daily"}
    mock_command.objects.get.return_value = command

    handler = RequireDaysSupplyHandler(event=event)
    effects = handler.compute()

    assert len(effects) == 1


@patch("command_validation.handlers.prescription_validation.Command")
def test_allows_commit_with_empty_string_days_supply(mock_command) -> None:
    """Test that the handler allows commit when days_supply is empty string."""
    event = Mock()
    event.target.id = "test-command-id"

    command = Mock()
    command.data = {"days_supply": "", "sig": "Take one daily"}
    mock_command.objects.get.return_value = command

    handler = RequireDaysSupplyHandler(event=event)
    effects = handler.compute()

    assert len(effects) == 0


@patch("command_validation.handlers.prescription_validation.Command")
def test_allows_commit_with_valid_days_supply(mock_command) -> None:
    """Test that the handler allows commit when days_supply is valid."""
    event = Mock()
    event.target.id = "test-command-id"

    command = Mock()
    command.data = {"days_supply": 30, "sig": "Take one daily"}
    mock_command.objects.get.return_value = command

    handler = RequireDaysSupplyHandler(event=event)
    effects = handler.compute()

    assert len(effects) == 0
