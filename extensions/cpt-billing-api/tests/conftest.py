"""Shared test fixtures for cpt-billing-api plugin."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a mock event object for handler initialization."""
    event = MagicMock()
    event.context = {"method": "POST", "path": "/billing/add-line-item"}
    event.target = MagicMock()
    return event


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock HTTP request object."""
    request = MagicMock()
    request.headers = {}
    request.json.return_value = {}
    return request


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    """Create mock secrets dictionary."""
    return {"simpleapi-api-key": "test-api-key-12345"}


@pytest.fixture
def mock_note() -> MagicMock:
    """Create a mock Note object."""
    note = MagicMock()
    note.id = "a74592ae-8a6c-4d0e-be07-99d3fb3713d1"
    note.dbid = 12345
    return note


@pytest.fixture
def mock_assessment() -> MagicMock:
    """Create a mock Assessment object."""
    assessment = MagicMock()
    assessment.id = "assessment-uuid-123"
    assessment.note_id = 12345
    return assessment
