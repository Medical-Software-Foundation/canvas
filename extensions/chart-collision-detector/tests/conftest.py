"""Shared test fixtures for chart-collision-detector plugin."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a mock event with patient chart context."""
    event = MagicMock()
    event.context = {
        "url": "/patient/patient-uuid-123/chart",
        "patient": {"id": "patient-uuid-123"},
        "user": {"staff": "staff-uuid-456"},
    }
    return event


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create a mock cache object."""
    cache = MagicMock()
    cache.get.return_value = None
    return cache
