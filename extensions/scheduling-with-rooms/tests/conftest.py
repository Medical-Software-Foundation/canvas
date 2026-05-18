"""Shared fixtures for scheduling_with_rooms tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event():
    event = MagicMock()
    event.context = {"patient": {"id": "patient-123"}}
    return event


@pytest.fixture
def mock_secrets():
    return {
        "FHIR_BASE_URL": "https://fumage-instance.canvasmedical.com",
        "FHIR_CLIENT_ID": "client-id",
        "FHIR_CLIENT_SECRET": "client-secret",
        "SCHEDULABLE_STAFF_ROLES": "MD,NP",
        "SCHEDULE_DURATIONS": "",
    }


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.query_params = {}
    request.headers = {}
    request.json.return_value = {}
    return request
