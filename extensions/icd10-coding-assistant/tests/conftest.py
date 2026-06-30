"""Shared test fixtures for the ICD-10 coding assistant plugin."""

import uuid
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_event() -> MagicMock:
    """Generic mock event for handler construction.

    Uses a real dict for context so SimpleAPI handlers can access context["method"]
    without a MagicMock fallback causing KeyError.
    """
    event = MagicMock()
    event.context = {"patient": {"id": "patient-abc123"}, "method": "GET", "path": "/"}
    return event


@pytest.fixture
def patient_id() -> str:
    return "patient-abc123"


@pytest.fixture
def mock_condition() -> MagicMock:
    """A mock Condition with a SNOMED coding (no ICD-10)."""
    condition = MagicMock()
    condition.id = str(uuid.uuid4())
    condition.dbid = 42

    coding = MagicMock()
    coding.system = "http://snomed.info/sct"
    coding.code = "44054006"
    coding.display = "Type 2 diabetes mellitus"

    condition.codings.all.return_value = [coding]
    return condition


@pytest.fixture
def mock_condition_no_codings() -> MagicMock:
    """A mock Condition with no codings at all."""
    condition = MagicMock()
    condition.id = str(uuid.uuid4())
    condition.dbid = 99
    condition.codings.all.return_value = []
    return condition
