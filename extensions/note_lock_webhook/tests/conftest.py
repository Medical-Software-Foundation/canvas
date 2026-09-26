"""Shared test fixtures for note_lock_webhook tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event() -> MagicMock:
    """A note state change event for a signed note."""
    event = MagicMock()
    event.context = {
        "state": "SGN",
        "note_id": "note-abc-123",
        "patient_id": "patient-xyz-789",
    }
    return event


@pytest.fixture
def secrets() -> dict:
    """Plugin secrets as configured in a Canvas instance."""
    return {"WEBHOOK_URL": "https://example.test/hook", "AUTH_TOKEN": "s3cret"}
