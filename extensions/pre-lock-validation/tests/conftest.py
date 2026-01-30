"""Shared test fixtures for pre-lock-validation plugin."""

import pytest
from unittest.mock import Mock

from canvas_sdk.events import EventType


@pytest.fixture
def mock_event():
    """Factory fixture to create mock events with configurable state."""
    def _create_event(state: str = "LKD"):
        event = Mock()
        event.type = EventType.NOTE_STATE_CHANGE_EVENT_PRE_CREATE
        event.context = {
            "state": state,
            "note_id": "test-note-id",
            "patient_id": "test-patient-id",
        }
        return event
    return _create_event


@pytest.fixture
def mock_command_chain():
    """Factory fixture to mock Command.objects.exclude(...).filter(...) chain."""
    def _create_chain(mock_command, commands: list):
        mock_filter_result = Mock()
        mock_filter_result.__iter__ = Mock(return_value=iter(commands))

        mock_exclude_result = Mock()
        mock_exclude_result.filter.return_value = mock_filter_result

        mock_command.objects.exclude.return_value = mock_exclude_result
        return mock_exclude_result
    return _create_chain


@pytest.fixture
def mock_command_filter():
    """Factory fixture to mock Command.objects.filter(...) with exists()."""
    def _create_filter(mock_command, exists: bool):
        mock_queryset = Mock()
        mock_queryset.exists.return_value = exists
        mock_command.objects.filter.return_value = mock_queryset
        return mock_queryset
    return _create_filter


def create_mock_command(schema_key: str) -> Mock:
    """Helper to create a mock command with a schema_key."""
    cmd = Mock()
    cmd.schema_key = schema_key
    return cmd
