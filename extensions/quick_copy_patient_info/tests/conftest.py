"""Shared fixtures for quick_copy_patient_info tests."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_event():
    """Factory: build a minimal event whose `target.id` is usable."""

    def _create(patient_id: str = "patient-1") -> Mock:
        event = Mock()
        event.target = SimpleNamespace(id=patient_id)
        event.context = {}
        return event

    return _create


def make_transactor(name: str = "Aetna") -> SimpleNamespace:
    """Build a Transactor (payer) shaped object."""
    return SimpleNamespace(name=name)


def make_coverage(
    payer_name: str = "Aetna",
    *,
    state: str = "active",
    stack: str = "IN_USE",
    coverage_rank: int = 1,
    issuer: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Build a Coverage-shaped object.

    `payer_name` is a shortcut that wraps a Transactor; pass `issuer=None`
    explicitly to test the no-issuer case.
    """
    if issuer is None and payer_name is not None:
        issuer = make_transactor(name=payer_name)
    return SimpleNamespace(
        state=state,
        stack=stack,
        coverage_rank=coverage_rank,
        issuer=issuer,
    )


def _build_filterable(items):
    """Wrap a list of namespace items in a queryset-like object supporting
    .filter(**kwargs), .select_related(*fields), .order_by(*fields), and
    .first() - the chain shapes the handler invokes."""

    class _Q:
        def __init__(self, data):
            self._data = list(data)

        def filter(self, **kwargs):
            def matches(item):
                for key, value in kwargs.items():
                    if getattr(item, key, None) != value:
                        return False
                return True

            return _Q([i for i in self._data if matches(i)])

        def select_related(self, *fields):
            # No-op for the fake - FK targets are already in-memory.
            return self

        def order_by(self, *fields):
            sorted_data = list(self._data)
            for field in reversed(fields):
                reverse = field.startswith("-")
                key = field.lstrip("-")
                sorted_data.sort(key=lambda i: getattr(i, key, 0), reverse=reverse)
            return _Q(sorted_data)

        def first(self):
            return self._data[0] if self._data else None

    return _Q(items)


def make_patient(
    *,
    first_name: str = "Jane",
    last_name: str = "Doe",
    birth_date: date | None = date(1985, 3, 14),
    preferred_pharmacy: dict | None = None,
    coverages: list | None = None,
) -> SimpleNamespace:
    """Build a Patient-shaped object for handler tests.

    `preferred_pharmacy` should be a dict matching the structure the
    Patient.preferred_pharmacy property returns (with `organization_name`,
    optional `phone`, `address`, `ncpdp_id`). Pass None to simulate no
    preferred pharmacy on file.

    `coverages` is a list of Coverage-shaped objects (use `make_coverage`).
    The handler accesses them through `patient.coverages.filter(...)`.
    """
    return SimpleNamespace(
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        preferred_pharmacy=preferred_pharmacy,
        coverages=_build_filterable(coverages or []),
    )
