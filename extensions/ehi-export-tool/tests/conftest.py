"""Shared fixtures for ehi-export-tool tests."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


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


def make_patient(
    *,
    pid: str = "p-1",
    first_name: str = "Ada",
    last_name: str = "Lovelace",
    birth_date: date | None = None,
    active: bool = True,
) -> SimpleNamespace:
    """Return a SimpleNamespace mimicking a Patient row."""
    if birth_date is None:
        birth_date = date(1990, 1, 2)
    return SimpleNamespace(
        id=pid,
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        active=active,
    )


class FakeQuerySet:
    """Minimal Django-queryset stand-in for patient-listing tests.

    Filtering/ordering are identity operations (we test response shaping and
    pagination, not Django's filter semantics); count() and slicing are real.
    """

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> "FakeQuerySet":
        return self

    def filter(self, *args, **kwargs) -> "FakeQuerySet":
        return self

    def annotate(self, *args, **kwargs) -> "FakeQuerySet":
        return self

    def order_by(self, *args) -> "FakeQuerySet":
        return self

    def count(self) -> int:
        return len(self._rows)

    def __getitem__(self, item):
        return self._rows[item]


@pytest.fixture
def fake_queryset() -> type[FakeQuerySet]:
    return FakeQuerySet
