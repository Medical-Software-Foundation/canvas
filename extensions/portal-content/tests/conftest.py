"""Shared test fixtures for portal_content plugin tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add project root to sys.path so portal_content.* imports resolve like in the runner.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_secrets() -> dict:
    """Secrets dict with FHIR credentials and all components enabled."""
    return {
        "CLIENT_ID": "test-client-id",
        "CLIENT_SECRET": "test-client-secret",
        "ENABLED_COMPONENTS": "",
        "NOTE_TYPES": "office-visit",
    }


@pytest.fixture
def mock_environment() -> dict:
    """Environment dict with the customer identifier used to build hosts."""
    return {"CUSTOMER_IDENTIFIER": "test-sandbox"}


@pytest.fixture
def mock_request() -> MagicMock:
    """A mock SimpleAPI request with patient headers and query params."""
    request = MagicMock()
    request.headers = {"canvas-logged-in-user-id": "patient-123"}
    request.query_params = MagicMock()
    request.query_params.get.return_value = None
    request.json.return_value = {}
    return request
