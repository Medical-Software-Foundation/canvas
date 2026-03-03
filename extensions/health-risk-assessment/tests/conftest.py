"""Shared test fixtures for Health Risk Assessment plugin."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event() -> MagicMock:
    """Create a base mock event."""
    event = MagicMock()
    event.context = {
        "note_id": "test-note-123",
        "patient": {"id": "test-patient-456"},
    }
    event.target = "test-patient-456"
    return event


@pytest.fixture
def mock_api_event() -> MagicMock:
    """Create a mock event for SimpleAPI handlers."""
    event = MagicMock()
    event.context = {
        "method": "POST",
        "path": "/submit-hra",
    }
    return event


@pytest.fixture
def mock_note() -> MagicMock:
    """Create a mock Note object."""
    note = MagicMock()
    note.id = "test-note-123"
    note.dbid = 123
    note.is_locked = False
    return note


@pytest.fixture
def mock_locked_note() -> MagicMock:
    """Create a mock locked Note object."""
    note = MagicMock()
    note.id = "test-note-123"
    note.dbid = 123
    note.is_locked = True
    return note


@pytest.fixture
def mock_questionnaire() -> MagicMock:
    """Create a mock Questionnaire object."""
    questionnaire = MagicMock()
    questionnaire.id = "questionnaire-uuid-789"
    questionnaire.code = "HRA_AWV"
    questionnaire.code_system = "INTERNAL"
    return questionnaire


@pytest.fixture
def mock_request() -> MagicMock:
    """Create a mock HTTP request."""
    request = MagicMock()
    request.method = "POST"
    request.path = "/submit-hra"
    return request


@pytest.fixture
def valid_form_data() -> dict:
    """Create valid form submission data."""
    return {
        "note_id": "test-note-123",
        "responses": {
            "HRA_GENERAL_HEALTH": "HRA_GENERAL_HEALTH_GOOD",
            "HRA_DIFF_STOOPING": "HRA_DIFF_STOOPING_NONE",
            "HRA_DIFF_LIFTING": "HRA_DIFF_LIFTING_LITTLE",
            "HRA_DIFF_REACHING": "HRA_DIFF_REACHING_NONE",
            "HRA_DIFF_WRITING": "HRA_DIFF_WRITING_NONE",
            "HRA_DIFF_WALKING_QUARTER": "HRA_DIFF_WALKING_QUARTER_SOME",
            "HRA_DIFF_HOUSEWORK": "HRA_DIFF_HOUSEWORK_NONE",
            "HRA_ADL_SHOPPING": "HRA_ADL_SHOPPING_NO",
            "HRA_ADL_SHOPPING_HELP": "HRA_ADL_SHOPPING_HELP_NA",
            "HRA_ADL_SHOPPING_HEALTH": "HRA_ADL_SHOPPING_HEALTH_NA",
            "HRA_ADL_MONEY": "HRA_ADL_MONEY_NO",
            "HRA_ADL_MONEY_HELP": "HRA_ADL_MONEY_HELP_NA",
            "HRA_ADL_MONEY_HEALTH": "HRA_ADL_MONEY_HEALTH_NA",
            "HRA_ADL_WALKING": "HRA_ADL_WALKING_YES",
            "HRA_ADL_WALKING_HELP": "HRA_ADL_WALKING_HELP_YES",
            "HRA_ADL_WALKING_HEALTH": "HRA_ADL_WALKING_HEALTH_NA",
            "HRA_ADL_LIGHT_HOUSEWORK": "HRA_ADL_LIGHT_HOUSEWORK_NO",
            "HRA_ADL_LIGHT_HOUSEWORK_HELP": "HRA_ADL_LIGHT_HOUSEWORK_HELP_NA",
            "HRA_ADL_LIGHT_HOUSEWORK_HEALTH": "HRA_ADL_LIGHT_HOUSEWORK_HEALTH_NA",
            "HRA_ADL_BATHING": "HRA_ADL_BATHING_DK",
            "HRA_ADL_BATHING_HELP": "HRA_ADL_BATHING_HELP_NA",
            "HRA_ADL_BATHING_HEALTH": "HRA_ADL_BATHING_HEALTH_YES",
        },
    }
