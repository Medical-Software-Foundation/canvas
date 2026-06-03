import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.query_params = {"patient_id": "patient-123", "note_id": "456"}
    request.headers = {}
    return request


@pytest.fixture
def mock_patient():
    patient = MagicMock()
    patient.id = "patient-123"
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    patient.birth_date = "1985-03-15"
    return patient


@pytest.fixture
def mock_note():
    note = MagicMock()
    note.dbid = 456
    note.datetime_of_service = "2025-01-15T10:00:00Z"
    return note


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.first_name = "Dr. John"
    provider.last_name = "Smith"
    provider.npi_number = "1234567890"
    role = MagicMock()
    role.public_abbreviation = "MD"
    provider.roles.filter.return_value.order_by.return_value.first.return_value = role
    return provider


@pytest.fixture
def mock_secrets():
    return {"simple-api-key": "test-secret-key-123", "display_timezone": "US/Eastern"}
