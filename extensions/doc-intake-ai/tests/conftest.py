"""Shared fixtures for doc-intake-ai tests."""

import sys
from typing import cast
from unittest.mock import MagicMock

import pytest

# Mock canvas_sdk.effects.data_integration before any plugin imports
mock_data_integration = MagicMock()
mock_data_integration.PrefillDocumentFields = MagicMock()
sys.modules.setdefault("canvas_sdk.effects.data_integration", mock_data_integration)

# Mock canvas_sdk.caching.plugins for cache access (not always installed)
try:
    import canvas_sdk.caching.plugins
except (ImportError, ModuleNotFoundError):
    mock_caching = MagicMock()
    sys.modules.setdefault("canvas_sdk.caching", mock_caching)
    sys.modules.setdefault("canvas_sdk.caching.plugins", mock_caching)

# Patch EventType to include DOCUMENT_RECEIVED if not present locally
from canvas_sdk.events import EventType

if not hasattr(EventType, "DOCUMENT_RECEIVED"):
    _DOCUMENT_RECEIVED_SENTINEL = 99999
    EventType.DOCUMENT_RECEIVED = _DOCUMENT_RECEIVED_SENTINEL
    # Also patch EventType.Name to handle our sentinel value
    _original_name = EventType.Name
    def _patched_name(number: int) -> str:
        if number == _DOCUMENT_RECEIVED_SENTINEL:
            return "DOCUMENT_RECEIVED"
        return cast(str, _original_name(number))
    EventType.Name = staticmethod(_patched_name)

# Patch canvas_sdk.v1.data with template models that may not exist locally
from canvas_sdk.v1 import data as sdk_data

for attr in (
    "ImagingReportTemplate",
    "ImagingReportTemplateField",
    "LabReportTemplate",
    "LabReportTemplateField",
    "SpecialtyReportTemplate",
    "SpecialtyReportTemplateField",
):
    if not hasattr(sdk_data, attr):
        setattr(sdk_data, attr, MagicMock())


@pytest.fixture
def sample_extraction_data() -> dict:
    """Sample extraction data from Extend AI."""
    return {
        "document_type": "lab_report",
        "loinc_codes": "11580-8, 3016-3",
        "snomed_codes": None,
        "test_names": "TSH, T4 Free",
        "patient_id": "MRN123",
        "patient_first_name": "John",
        "patient_last_name": "Doe",
        "date_of_birth": "1990-01-15",
        "practitioner_npi": "1234567890",
        "practitioner_first_name": "Jane",
        "practitioner_last_name": "Smith",
    }


@pytest.fixture
def sample_metadata() -> dict:
    """Sample metadata with OCR confidence scores."""
    return {
        "document_type": {"ocrConfidence": 0.95},
        "loinc_codes": {"ocrConfidence": 0.88},
        "patient_id": {"ocrConfidence": 0.92},
        "patient_first_name": {"ocrConfidence": 0.85},
    }


@pytest.fixture
def sample_available_types() -> list[dict]:
    """Sample available document types from event context."""
    return [
        {
            "key": "lab_report",
            "name": "Lab Report",
            "report_type": "LAB",
            "template_type": "LabReportTemplate",
        },
        {
            "key": "imaging_report",
            "name": "Imaging Report",
            "report_type": "IMAGING",
            "template_type": "ImagingReportTemplate",
        },
        {
            "key": "specialty_report",
            "name": "Specialty Report",
            "report_type": "SPECIALTY",
            "template_type": "SpecialtyReportTemplate",
        },
    ]
