from datetime import date, datetime
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event() -> MagicMock:
    """Mock event for handler initialization."""
    return MagicMock()


@pytest.fixture
def mock_request() -> MagicMock:
    """Mock SimpleAPI request."""
    request = MagicMock()
    request.path_params = MagicMock()
    return request


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    """Mock secrets for API key authentication."""
    return {"simpleapi-api-key": "test-api-key-12345"}


def _make_lab_value_coding(
    *,
    name: str = "Hemoglobin A1c",
    code: str = "4548-4",
    system: str = "http://loinc.org",
) -> MagicMock:
    coding = MagicMock()
    coding.name = name
    coding.code = code
    coding.system = system
    return coding


def _make_lab_value(
    *,
    id: str = "lab-value-uuid-1",
    value: str = "6.5",
    units: str = "%",
    reference_range: str = "4.0-5.6",
    abnormal_flag: str = "H",
    observation_status: str = "final",
    low_threshold: str = "4.0",
    high_threshold: str = "5.6",
    comment: str = "Elevated A1c",
    created: datetime | None = datetime(2025, 1, 15, 10, 0, 0),
    modified: datetime | None = datetime(2025, 1, 15, 10, 0, 0),
    test_id: str | None = "lab-test-uuid-1",
    coding: MagicMock | None = None,
) -> MagicMock:
    lab_value = MagicMock()
    lab_value.id = id
    lab_value.value = value
    lab_value.units = units
    lab_value.reference_range = reference_range
    lab_value.abnormal_flag = abnormal_flag
    lab_value.observation_status = observation_status
    lab_value.low_threshold = low_threshold
    lab_value.high_threshold = high_threshold
    lab_value.comment = comment
    lab_value.created = created
    lab_value.modified = modified
    lab_value.test_id = test_id
    lab_value.codings.first.return_value = coding
    return lab_value


@pytest.fixture
def make_lab_value() -> Callable[..., MagicMock]:
    """Factory for LabValue mocks."""
    return _make_lab_value


@pytest.fixture
def make_lab_value_coding() -> Callable[..., MagicMock]:
    """Factory for LabValueCoding mocks."""
    return _make_lab_value_coding


@pytest.fixture
def mock_lab_value_with_coding() -> MagicMock:
    return _make_lab_value(coding=_make_lab_value_coding())


@pytest.fixture
def mock_lab_value_no_coding() -> MagicMock:
    return _make_lab_value(
        id="lab-value-uuid-2",
        value="110",
        units="mg/dL",
        reference_range="70-100",
        abnormal_flag="H",
        comment="",
        coding=None,
    )


@pytest.fixture
def mock_lab_test(mock_lab_value_with_coding: MagicMock) -> MagicMock:
    """A single LabTest mock with one value nested under it."""
    lab_test = MagicMock()
    lab_test.id = "lab-test-uuid-1"
    lab_test.ontology_test_name = "Hemoglobin A1c"
    lab_test.ontology_test_code = "4548-4"
    lab_test.values.all.return_value = [mock_lab_value_with_coding]
    return lab_test


@pytest.fixture
def mock_ordering_provider() -> MagicMock:
    provider = MagicMock()
    provider.id = "provider-uuid-456"
    provider.first_name = "Jane"
    provider.last_name = "Smith"
    provider.npi_number = "1234567890"
    return provider


@pytest.fixture
def mock_lab_order(mock_ordering_provider: MagicMock) -> MagicMock:
    """LabOrder mock with provider, partner, and no reason_conditions by default."""
    lab_order = MagicMock()
    lab_order.id = "lab-order-uuid-123"
    lab_order.ontology_lab_partner = "Quest Diagnostics"
    lab_order.comment = "Routine check"
    lab_order.date_ordered = datetime(2025, 1, 14, 9, 0, 0)
    lab_order.ordering_provider = mock_ordering_provider
    lab_order.reasons.filter.return_value.prefetch_related.return_value = []
    return lab_order


@pytest.fixture
def mock_lab_report(
    mock_lab_test: MagicMock,
    mock_lab_order: MagicMock,
    mock_lab_value_with_coding: MagicMock,
) -> MagicMock:
    """LabReport mock wired up against the SDK prefetch helper."""
    lab_report = MagicMock()
    lab_report.id = "lab-report-uuid-789"
    lab_report.dbid = 999
    lab_report.created = datetime(2025, 1, 15, 8, 0, 0)
    lab_report.modified = datetime(2025, 1, 15, 10, 0, 0)

    lab_report.patient.id = "patient-uuid-111"
    lab_report.patient.first_name = "John"
    lab_report.patient.last_name = "Doe"
    lab_report.patient.birth_date = date(1980, 5, 15)

    lab_report.result_tests = [mock_lab_test]
    lab_report.values.all.return_value = [mock_lab_value_with_coding]
    lab_report.laborder_set.select_related.return_value.filter.return_value = [mock_lab_order]
    return lab_report


@pytest.fixture
def make_reason_with_conditions() -> Callable[..., MagicMock]:
    """Factory for LabOrderReason mocks. conditions is a list of (condition, entered_in_error)."""

    def _factory(conditions: list[tuple[str, list[tuple[str, str, str]], str | None]]) -> MagicMock:
        reason = MagicMock()
        reason_condition_mocks: list[Any] = []
        for condition_id, codings, entered_in_error in conditions:
            condition = MagicMock()
            condition.id = condition_id
            condition.entered_in_error_id = entered_in_error
            coding_mocks: list[Any] = []
            for code, display, system in codings:
                c = MagicMock()
                c.code = code
                c.display = display
                c.system = system
                coding_mocks.append(c)
            condition.codings.all.return_value = coding_mocks
            rc = MagicMock()
            rc.condition = condition
            reason_condition_mocks.append(rc)
        reason.reason_conditions.all.return_value = reason_condition_mocks
        return reason

    return _factory
