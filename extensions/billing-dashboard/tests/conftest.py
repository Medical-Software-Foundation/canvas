"""Shared test fixtures for billing_dashboard tests."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a base mock event."""
    event = MagicMock()
    event.context = {
        "headers": {"canvas-logged-in-user-id": "staff-abc-123"},
    }
    return event


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock SimpleAPI request with defaults."""
    request = MagicMock()
    request.query_params = {}
    request.path_params = {}
    return request
