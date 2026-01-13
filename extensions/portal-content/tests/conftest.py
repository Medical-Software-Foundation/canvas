"""Shared test fixtures for portal_content plugin tests."""

import sys
from pathlib import Path

# Add project root to sys.path so portal_content.* imports work like in deployed environment
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_secrets():
    """Create mock secrets dictionary."""
    return {
        "CLIENT_ID": "test-client-id",
        "CLIENT_SECRET": "test-client-secret",
        "ENABLED_COMPONENTS": "",
    }


@pytest.fixture
def mock_environment():
    """Create mock environment dictionary."""
    return {"CUSTOMER_IDENTIFIER": "test-sandbox"}


@pytest.fixture
def mock_request():
    """Create a mock request object."""
    request = MagicMock()
    request.headers = MagicMock()
    request.headers.get.return_value = "patient-123"
    request.query_params = MagicMock()
    request.query_params.get.return_value = None
    request.json.return_value = {}
    return request


@pytest.fixture
def mock_patient_credentials():
    """Create mock session credentials for a patient user."""
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "patient-123", "type": "Patient"}
    return credentials


@pytest.fixture
def mock_staff_credentials():
    """Create mock session credentials for a staff user."""
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "staff-456", "type": "Staff"}
    return credentials


@pytest.fixture
def mock_fhir_client():
    """Create a mock FHIR client."""
    client = MagicMock()
    client.base_url = "https://fumage-test-sandbox.canvasmedical.com"
    client.token = "test-token-12345"
    return client


@pytest.fixture
def mock_document_reference():
    """Create a mock FHIR DocumentReference resource."""
    return {
        "resourceType": "DocumentReference",
        "id": "doc-123",
        "status": "current",
        "subject": {"reference": "Patient/patient-123"},
        "date": "2024-01-15T10:30:00Z",
        "description": "Test Document",
        "type": {
            "coding": [{"system": "http://loinc.org", "code": "11488-4", "display": "Consult Note"}],
            "text": "Test Document Type",
        },
        "content": [{"attachment": {"url": "https://example.com/document.pdf", "contentType": "application/pdf"}}],
        "context": {"period": {"start": "2024-01-15T09:00:00Z"}},
    }


@pytest.fixture
def mock_bundle_with_entries(mock_document_reference):
    """Create a mock FHIR Bundle with entries."""
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": 1,
        "entry": [{"resource": mock_document_reference}],
    }


@pytest.fixture
def mock_empty_bundle():
    """Create a mock empty FHIR Bundle."""
    return {"resourceType": "Bundle", "type": "searchset", "total": 0, "entry": []}


@pytest.fixture
def api_instance(mock_secrets, mock_environment, mock_request):
    """Create a PortalContentAPI instance for testing."""
    from portal_content.api.portal_api import PortalContentAPI

    api = PortalContentAPI()
    api.secrets = mock_secrets
    api.environment = mock_environment
    api.request = mock_request
    return api
