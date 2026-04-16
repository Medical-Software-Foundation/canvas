"""Shared test fixtures for prescription favorites plugin."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_patient() -> MagicMock:
    """Create a mock patient object."""
    patient = MagicMock()
    patient.id = "test-patient-123"
    patient.first_name = "John"
    patient.last_name = "Doe"
    return patient


@pytest.fixture
def mock_note() -> MagicMock:
    """Create a mock note object."""
    note = MagicMock()
    note.id = "test-note-456"
    note.dbid = "test-note-dbid-456"
    note.datetime_of_service = "2024-01-10"
    note.modified = "2024-01-10T15:45:00"
    return note


@pytest.fixture
def mock_user() -> MagicMock:
    """Create a mock user object."""
    user = MagicMock()
    user.id = "test-user-789"
    user.username = "testdoc"
    return user


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock request object."""
    request = MagicMock()
    request.user = MagicMock()
    request.user.id = "test-user-789"
    request.headers = MagicMock()
    request.headers.get = MagicMock(side_effect=lambda key, default="": "test-staff-123" if key == "canvas-logged-in-user-id" else default)
    return request
