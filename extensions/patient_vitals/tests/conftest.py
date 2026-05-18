"""Shared fixtures for patient_vitals tests.

The test suite is pure unit/mock — it does not stand up Django or hit the DB.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Mirror the path setup used by sibling plugin test suites so
# ``import patient_vitals`` resolves from this repo, not the installed package.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_secrets() -> dict:
    """This plugin has no declared secrets, but downstream code reads `secrets`."""
    return {}


@pytest.fixture
def mock_environment() -> dict:
    """Mock environment dictionary."""
    return {"CUSTOMER_IDENTIFIER": "test-sandbox"}


@pytest.fixture
def mock_request():
    """A request whose headers map ``canvas-logged-in-user-id`` to a patient id."""
    request = MagicMock()
    request.headers = MagicMock()
    request.headers.get.return_value = "patient-123"
    request.json.return_value = {}
    return request


@pytest.fixture
def mock_patient_credentials():
    """Logged-in patient session credentials."""
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "patient-123", "type": "Patient"}
    return credentials


@pytest.fixture
def mock_staff_credentials():
    """Logged-in staff session credentials (should be rejected by the API)."""
    credentials = MagicMock()
    credentials.logged_in_user = {"id": "staff-456", "type": "Staff"}
    return credentials


def make_obs(
    *,
    name: str | None = None,
    value: str | None = None,
    loinc: str | None = None,
    effective_datetime: datetime | None = None,
) -> SimpleNamespace:
    """Build a stand-in for a vital-signs Observation row.

    Only the attributes that ``vitals_data._resolve_canonicals`` and
    ``vitals_data._normalize_point`` reach for are populated.
    """
    if effective_datetime is None:
        effective_datetime = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    codings = MagicMock()
    codings.first.return_value = SimpleNamespace(code=loinc) if loinc else None
    return SimpleNamespace(
        name=name,
        value=value,
        codings=codings,
        effective_datetime=effective_datetime,
    )


@pytest.fixture
def make_observation():
    """Expose the make_obs helper as a fixture."""
    return make_obs
