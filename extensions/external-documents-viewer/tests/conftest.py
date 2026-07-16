from typing import Any

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_patient() -> MagicMock:
    """Mock Patient ORM object with typical fields used in the template."""
    patient = MagicMock()
    patient.id = "patient-uuid-123"
    patient.first_name = "Test"
    patient.last_name = "Patient"
    patient.birth_date = "2000-01-01"
    return patient


@pytest.fixture
def mock_secrets() -> dict[str, str]:
    """Mock secrets dict with S3 credentials."""
    return {
        "S3_KEY": "test-access-key",
        "S3_SECRET": "test-secret-key",
        "S3_REGION": "us-west-2",
        "S3_BUCKET": "test-bucket",
    }


@pytest.fixture
def sample_documents() -> list[dict[str, Any]]:
    """Sample document list matching the per-patient JSON structure."""
    return [
        {
            "title": "Annual Physical Examination",
            "category": "Clinical Note",
            "date": "2025-10-20",
            "s3_key": "PATIENT_DIR/annual_physical.pdf",
        },
        {
            "title": "MRI Scan",
            "category": "Imaging",
            "date": "2025-11-29",
            "s3_key": "PATIENT_DIR/mri_scan.pdf",
        },
        {
            "title": "Refill Request",
            "category": "Order",
            "date": "2026-01-29",
            "s3_key": "PATIENT_DIR/refill_request.pdf",
        },
    ]
