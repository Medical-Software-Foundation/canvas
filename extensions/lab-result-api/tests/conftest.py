import pytest
from unittest.mock import MagicMock
from datetime import datetime


@pytest.fixture
def mock_event():
    """Create a mock event for handler initialization."""
    event = MagicMock()
    event.context = {"method": "GET", "path": "/lab-result/test-id"}
    return event


@pytest.fixture
def mock_request():
    """Create a mock SimpleAPI request."""
    request = MagicMock()
    request.path_params = MagicMock()
    request.headers = {}
    request.json.return_value = {}
    return request


@pytest.fixture
def mock_lab_value_with_coding():
    """Create a mock LabValue instance with coding information."""
    lab_value = MagicMock()
    lab_value.id = "lab-value-uuid-1"
    lab_value.value = "6.5"
    lab_value.units = "%"
    lab_value.reference_range = "4.0-5.6"
    lab_value.abnormal_flag = "high"
    lab_value.observation_status = "final"
    lab_value.low_threshold = "4.0"
    lab_value.high_threshold = "5.6"
    lab_value.comment = "Elevated A1c"
    lab_value.created = datetime(2025, 1, 15, 10, 0, 0)
    lab_value.modified = datetime(2025, 1, 15, 10, 0, 0)

    # Mock coding
    mock_coding = MagicMock()
    mock_coding.display = "Hemoglobin A1c"
    mock_coding.code = "4548-4"
    mock_coding.system = "http://loinc.org"

    mock_codings = MagicMock()
    mock_codings.exists.return_value = True
    mock_codings.first.return_value = mock_coding
    lab_value.codings = mock_codings

    return lab_value


@pytest.fixture
def mock_lab_value_no_coding():
    """Create a mock LabValue instance without coding information."""
    lab_value = MagicMock()
    lab_value.id = "lab-value-uuid-2"
    lab_value.value = "110"
    lab_value.units = "mg/dL"
    lab_value.reference_range = "70-100"
    lab_value.abnormal_flag = "high"
    lab_value.observation_status = "final"
    lab_value.low_threshold = "70"
    lab_value.high_threshold = "100"
    lab_value.comment = None
    lab_value.created = datetime(2025, 1, 15, 10, 0, 0)
    lab_value.modified = datetime(2025, 1, 15, 10, 0, 0)

    mock_codings = MagicMock()
    mock_codings.exists.return_value = False
    lab_value.codings = mock_codings

    return lab_value


@pytest.fixture
def mock_lab_order():
    """Create a mock LabOrder instance with ordering provider."""
    lab_order = MagicMock()
    lab_order.id = "lab-order-uuid-123"
    lab_order.ontology_lab_partner = "Quest Diagnostics"

    # Mock ordering provider
    lab_order.ordering_provider.id = "provider-uuid-456"
    lab_order.ordering_provider.first_name = "Jane"
    lab_order.ordering_provider.last_name = "Smith"
    lab_order.ordering_provider.npi = "1234567890"

    return lab_order


@pytest.fixture
def mock_lab_report(mock_lab_value_with_coding, mock_lab_value_no_coding, mock_lab_order):
    """Create a mock LabReport instance with all required fields."""
    lab_report = MagicMock()
    lab_report.id = "lab-report-uuid-789"
    lab_report.dbid = 999
    lab_report.created = datetime(2025, 1, 15, 8, 0, 0)
    lab_report.modified = datetime(2025, 1, 15, 10, 0, 0)

    # Mock patient
    lab_report.patient.id = "patient-uuid-111"
    lab_report.patient.first_name = "John"
    lab_report.patient.last_name = "Doe"
    lab_report.patient.birth_date = datetime(1980, 5, 15).date()

    # Mock originator
    lab_report.originator.person_subclass.id = "staff-uuid-222"
    lab_report.originator.person_subclass.first_name = "Alice"
    lab_report.originator.person_subclass.last_name = "Johnson"
    lab_report.originator.is_staff = True

    # Mock lab values (test results)
    mock_values = MagicMock()
    mock_values.all.return_value = [mock_lab_value_with_coding, mock_lab_value_no_coding]
    lab_report.values = mock_values

    # Mock lab orders
    mock_laborder_set = MagicMock()
    mock_laborder_set.all.return_value = [mock_lab_order]
    lab_report.laborder_set = mock_laborder_set

    return lab_report


@pytest.fixture
def mock_secrets():
    """Create mock secrets for API key authentication."""
    return {
        "simpleapi-api-key": "test-api-key-12345"
    }
