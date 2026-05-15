"""Shared fixtures for provider_availability_manager tests."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event():
    event = MagicMock()
    event.context = {}
    return event


@pytest.fixture
def mock_secrets():
    return {
        "SCHEDULABLE_STAFF_ROLES": "MD,NP",
    }


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.query_params = {}
    request.headers = {}
    request.json.return_value = {}
    return request
