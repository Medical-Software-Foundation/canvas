"""Shared test fixtures for github-discussions plugin tests."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_event():
    """Create a basic mock event with command and user context."""
    event = MagicMock()
    event.context = {
        "search_term": "test",
        "user": {"staff": "staff-123"},
        "results": [],
        "method": "GET",
        "path": "/test-path"
    }
    return event


@pytest.fixture
def mock_medication_result():
    """Create a mock medication search result."""
    return {
        "text": "acetaminophen 500 mg tablet",
        "disabled": False,
        "description": None,
        "annotations": None,
        "extra": {
            "coding": [
                {
                    "code": 206813,
                    "display": "acetaminophen 500 mg tablet",
                    "system": "http://www.fdbhealth.com/"
                }
            ]
        },
        "value": {}
    }


@pytest.fixture
def mock_medication():
    """Create a mock medication with high-risk drug."""
    med = MagicMock()
    med.id = "med-123"
    med.status = "active"

    # Mock the codings relationship
    coding = MagicMock()
    coding.display = "Warfarin 5mg Tablet"
    med.codings.first.return_value = coding

    return med


@pytest.fixture
def mock_patient():
    """Create a mock patient."""
    patient = MagicMock()
    patient.id = "test-patient-123"
    patient.first_name = "John"
    patient.last_name = "Doe"
    return patient


@pytest.fixture
def mock_environment():
    """Create mock environment variables."""
    return {
        "CUSTOMER_IDENTIFIER": "test-customer",
    }


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    websocket = MagicMock()
    websocket.channel = "test-patient-123"
    websocket.headers = {}
    websocket.logged_in_user = {"id": "staff-456", "type": "Staff"}
    return websocket
