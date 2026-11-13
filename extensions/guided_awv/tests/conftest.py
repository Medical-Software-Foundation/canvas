"""Shared test fixtures for the guided-awv plugin."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a base mock event object."""
    event = MagicMock()
    event.context = {}
    return event


@pytest.fixture
def mock_patient() -> MagicMock:
    """Create a mock patient object."""
    import datetime

    patient = MagicMock()
    patient.id = "patient-abc-123"
    patient.first_name = "Jane"
    patient.last_name = "Medicare"
    patient.birth_date = datetime.date(1950, 6, 15)
    patient.sex_at_birth = "F"
    return patient


@pytest.fixture
def mock_note() -> MagicMock:
    """Create a mock note object with a note_type_version."""
    note = MagicMock()
    note.id = "note-uuid-456"
    note.note_type_version_id = "ntype-001"
    note.note_type_version = MagicMock()
    note.note_type_version.name = "Annual Wellness Visit"
    return note


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock HTTP request object."""
    request = MagicMock()
    request.method = "POST"
    return request


@pytest.fixture(autouse=True)
def _mock_form_state_cache() -> Generator[MagicMock, None, None]:
    """Auto-mock _save_form_state so tests don't need plugin cache context."""
    with patch("guided_awv.api.awv_api._save_form_state") as mock_save:
        yield mock_save
