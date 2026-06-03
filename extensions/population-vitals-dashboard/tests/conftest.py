"""Shared fixtures for population-vitals-dashboard tests."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ── credential helpers ────────────────────────────────────────────────────────


@pytest.fixture
def mock_staff_credentials() -> MagicMock:
    """Session credentials for a logged-in staff member."""
    creds = MagicMock()
    creds.logged_in_user = {"id": "staff-abc", "type": "Staff"}
    return creds


@pytest.fixture
def mock_patient_credentials() -> MagicMock:
    """Session credentials for a logged-in patient (should be rejected)."""
    creds = MagicMock()
    creds.logged_in_user = {"id": "patient-xyz", "type": "Patient"}
    return creds


@pytest.fixture
def mock_request() -> MagicMock:
    """A minimal mock HTTP request with staff session headers."""
    req = MagicMock()
    req.headers = {"canvas-logged-in-user-id": "staff-abc", "canvas-logged-in-user-type": "Staff"}
    req.query_params = {}
    return req


# ── date helpers ──────────────────────────────────────────────────────────────

FIXED_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
FIXED_START = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def default_date_window() -> tuple[datetime, datetime]:
    return FIXED_START, FIXED_NOW


# ── observation helpers ───────────────────────────────────────────────────────


def make_obs(
    *,
    name: str = "weight",
    value: str = "180.0",
    category: str = "vital-signs",
    effective_datetime: datetime | None = None,
    patient_id: str = "p-1",
) -> SimpleNamespace:
    """Return a SimpleNamespace mimicking an Observation row."""
    if effective_datetime is None:
        effective_datetime = FIXED_NOW
    return SimpleNamespace(
        name=name,
        value=value,
        category=category,
        effective_datetime=effective_datetime,
        patient_id=patient_id,
        entered_in_error=None,
    )


@pytest.fixture
def make_observation() -> object:
    """Expose make_obs as a fixture callable."""
    return make_obs
