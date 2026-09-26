"""Shared test fixtures for doxy_in_chart plugin."""
import sys
from unittest.mock import MagicMock

import pytest


# Create a proper base class for ActionButton
class MockActionButton:
    """Mock base class for ActionButton that allows inheritance."""

    class ButtonLocation:
        NOTE_HEADER = "note_header"

    BUTTON_TITLE = ""
    BUTTON_KEY = ""
    BUTTON_LOCATION = None

    def __init__(self):
        self.event = None


# Mock Canvas SDK modules before any imports
sys.modules["canvas_sdk"] = MagicMock()
sys.modules["canvas_sdk.effects"] = MagicMock()
sys.modules["canvas_sdk.effects.launch_modal"] = MagicMock()
sys.modules["canvas_sdk.handlers"] = MagicMock()

action_button_mock = MagicMock()
action_button_mock.ActionButton = MockActionButton
sys.modules["canvas_sdk.handlers.action_button"] = action_button_mock

sys.modules["canvas_sdk.templates"] = MagicMock()
sys.modules["canvas_sdk.templates.utils"] = MagicMock()
sys.modules["canvas_sdk.v1"] = MagicMock()
sys.modules["canvas_sdk.v1.data"] = MagicMock()
sys.modules["canvas_sdk.v1.data.note"] = MagicMock()
sys.modules["canvas_sdk.v1.data.appointment"] = MagicMock()


@pytest.fixture
def mock_event():
    """Create a mock event with note_id context."""
    event = MagicMock()
    event.context = {"note_id": 42}
    return event
