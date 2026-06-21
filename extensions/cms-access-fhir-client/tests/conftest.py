"""Shared fixtures for cms-access-fhir-client tests."""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def full_secrets():
    return {
        "ACCESS_BASE_URL": "https://api.access.cms.gov/fhir",
        "ACCESS_OAUTH_CLIENT_ID": "test-client-id",
        "ACCESS_OAUTH_CLIENT_SECRET": "test-client-secret",
        "ACCESS_OAUTH_TOKEN_URL": "https://auth.cms.gov/token",
        "ACCESS_PARTICIPANT_ID": "ACCESS1234",
        "ACCESS_SHOW_BANNER": "true",
        "ACCESS_SHOW_PROFILE_FIELD": "true",
    }


@pytest.fixture
def mock_patient():
    patient = MagicMock()
    patient.id = "patient-uuid-123"
    patient.dbid = 1
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    return patient


@pytest.fixture
def mock_alignment(mock_patient):
    alignment = MagicMock()
    alignment.dbid = 1
    alignment.patient = mock_patient
    alignment.patient_id = mock_patient.dbid
    alignment.alignment_id = "align-abc"
    alignment.track = "eCKM"
    alignment.tier = "initial"
    alignment.status = "aligned"
    alignment.care_start_date = "2026-01-01"
    alignment.care_end_date = None
    alignment.submission_state = ""
    alignment.submission_status_url = ""
    alignment.submission_op = ""
    alignment.poll_attempts = 0
    alignment.last_poll_at = None
    alignment.submission_started_at = None
    return alignment
