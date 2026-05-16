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


def make_contact_point(
    value: str,
    system: str = "phone",
    state: str = "active",
    rank: int = 1,
    use: str = "mobile",
) -> SimpleNamespace:
    """Build a PatientContactPoint-shaped object."""
    return SimpleNamespace(
        value=value,
        system=system,
        state=state,
        rank=rank,
        use=use,
    )


def make_address(
    line1: str = "",
    line2: str = "",
    city: str = "",
    state_code: str = "",
    postal_code: str = "",
    use: str = "home",
    state: str = "active",
) -> SimpleNamespace:
    """Build a PatientAddress-shaped object."""
    return SimpleNamespace(
        line1=line1,
        line2=line2,
        city=city,
        state_code=state_code,
        postal_code=postal_code,
        use=use,
        state=state,
    )


def _build_filterable(items):
    """Wrap a list of namespace items in a queryset-like object that supports
    .filter(**kwargs), .order_by(*args), .first() in the order the handler
    invokes them."""

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
    contact_points: list | None = None,
    addresses: list | None = None,
) -> SimpleNamespace:
    """Build a Patient-shaped object for handler tests.

    `contact_points` and `addresses` accept lists of SimpleNamespace objects
    (use `make_contact_point` / `make_address`). They are exposed via the
    `telecom` and `addresses` related-manager attributes that the handler
    uses, supporting the `.filter().order_by().first()` chain.
    """
    return SimpleNamespace(
        first_name=first_name,
        last_name=last_name,
        birth_date=birth_date,
        telecom=_build_filterable(contact_points or []),
        addresses=_build_filterable(addresses or []),
    )
