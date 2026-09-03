"""Shared fixtures for supervisor_cosign tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event():
    """A mock Canvas SDK event with sensible defaults."""
    event = MagicMock()
    event.target.id = "target-uuid-123"
    event.context = {}
    event.name = "NOTE_STATE_CHANGE_EVENT_CREATED"
    return event


def make_simple_api_handler(handler_cls, json_body=None, path_params=None, query_params=None):
    """Build a SimpleAPI handler with a mocked request, bypassing __init__ signature."""
    handler = handler_cls.__new__(handler_cls)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler.request = MagicMock()
    handler.request.path_params = path_params or {}
    handler.request.query_params = query_params or {}
    handler.request.json.return_value = json_body or {}
    return handler
