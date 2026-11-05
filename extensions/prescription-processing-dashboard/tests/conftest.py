"""Shared test fixtures for prescription processing dashboard tests."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event():
    """Create a mock event for handler instantiation."""
    event = MagicMock()
    event.context = {}
    event.target = MagicMock()
    event.target.id = "test-target"
    return event


@pytest.fixture
def mock_simple_api_event():
    """Create a mock event for SimpleAPI handler instantiation."""
    event = MagicMock()
    event.context = {
        "method": "GET",
        "path": "/plugin-io/api/prescription_processing_dashboard/app/dashboard",
    }
    event.target = MagicMock()
    event.target.id = "test-target"
    return event


@pytest.fixture
def mock_staff():
    """Create a mock staff member."""
    staff = MagicMock()
    staff.id = "staff-123"
    staff.first_name = "Jane"
    staff.last_name = "Doe"
    return staff


@pytest.fixture
def mock_patient():
    """Create a mock patient."""
    patient = MagicMock()
    patient.id = "patient-123"
    patient.first_name = "John"
    patient.last_name = "Smith"
    return patient


@pytest.fixture
def mock_note():
    """Create a mock note."""
    note = MagicMock()
    note.id = "note-123"
    note.uuid = "note-uuid-123"
    return note


@pytest.fixture
def mock_prescription_command(mock_patient, mock_note):
    """Create a mock prescription command."""
    command = MagicMock()
    command.id = "command-123"
    command.schema_key = "prescribe"
    command.patient = mock_patient
    command.note = mock_note
    command.data = {
        "prescribe": {"text": "Lisinopril 10mg", "value": "12345"},
        "prescriber": {"text": "Dr. Smith", "value": 456},
        "pharmacy": {"text": "CVS Pharmacy", "value": "pharmacy-789"},
        "days_supply": 30,
        "sig": "Take 1 tablet by mouth daily",
    }
    command.originator = MagicMock()
    command.originator.staff = MagicMock()
    command.originator.staff.first_name = "Dr."
    command.originator.staff.last_name = "Smith"
    return command


@pytest.fixture
def mock_request():
    """Create a mock request object."""
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": "staff-123"}
    request.query_params = {}
    return request


@pytest.fixture
def mock_session_credentials():
    """Create mock session credentials."""
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "staff-123", "type": "Staff"}
    return credentials
