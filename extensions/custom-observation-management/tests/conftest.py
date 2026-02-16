"""Shared test fixtures for custom-observation-management plugin."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a mock event object for handler initialization."""
    event = MagicMock()
    event.context = {"method": "GET", "path": "/observations"}
    event.target = MagicMock()
    return event


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock HTTP request object."""
    request = MagicMock()
    request.headers = {}
    request.query_params = {}
    request.path_params = {}
    request.json.return_value = {}
    return request


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    """Create mock secrets dictionary."""
    return {"simpleapi-api-key": "test-api-key-12345"}


@pytest.fixture
def mock_observation() -> MagicMock:
    """Create a mock Observation object."""
    observation = MagicMock()
    observation.id = "obs-uuid-123"
    observation.name = "Blood Pressure"
    observation.category = "vital-signs"
    observation.value = "120/80"
    observation.units = "mmHg"
    observation.note_id = 12345
    observation.effective_datetime = None

    # Mock patient
    observation.patient = MagicMock()
    observation.patient.id = "patient-uuid-123"
    observation.patient.first_name = "John"
    observation.patient.last_name = "Doe"

    # Mock is_member_of (organization)
    observation.is_member_of = None

    # Mock codings
    observation.codings.all.return_value = []

    # Mock components
    observation.components.all.return_value = []

    # Mock value_codings
    observation.value_codings.all.return_value = []

    return observation


@pytest.fixture
def mock_patient() -> MagicMock:
    """Create a mock Patient object."""
    patient = MagicMock()
    patient.id = "patient-uuid-123"
    patient.first_name = "John"
    patient.last_name = "Doe"
    return patient


@pytest.fixture
def mock_note() -> MagicMock:
    """Create a mock Note object."""
    note = MagicMock()
    note.id = "note-uuid-123"
    note.dbid = 12345
    note.datetime_of_service = None
    return note
