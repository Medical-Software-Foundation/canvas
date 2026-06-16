"""Shared fixtures for sleep-study-visualizer tests."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_diagnose_event():
    """Mock COMMAND__FORM__GET_ADDITIONAL_FIELDS event for a diagnose command."""
    event = MagicMock()
    event.context = {"schema_key": "diagnose", "purpose": "form"}
    event.target.id = "cmd-uuid-1234"
    return event


@pytest.fixture
def mock_diagnose_post_commit_event():
    """Mock DIAGNOSE_COMMAND__POST_COMMIT event."""
    event = MagicMock()
    event.target.id = "cmd-uuid-5678"
    event.context = {
        "patient": {"id": "patient-abc"},
        "note": {"uuid": "note-uuid-9999"},
        "fields": {
            "diagnose": {
                "text": "Obstructive sleep apnea",
                "extra": {"coding": [{"code": "G47.33", "display": "Obstructive sleep apnea"}]},
            }
        },
    }
    return event
