"""Shared fixtures for lab_order_validation tests."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest


def _coverage(
    *,
    rank: int | None = 1,
    start: date | None = None,
    end: date | None = None,
    issuer: object = None,
    subscriber: object = None,
    state: str = "active",
) -> MagicMock:
    cov = MagicMock()
    cov.coverage_rank = rank
    cov.coverage_start_date = start if start is not None else date(2020, 1, 1)
    cov.coverage_end_date = end
    cov.issuer = issuer
    cov.subscriber = subscriber
    cov.state = state
    return cov


def _issuer(
    *,
    dbid: int = 1,
    name: str = "Acme Health",
    addresses: list | None = None,
    phones: list | None = None,
) -> MagicMock:
    issuer = MagicMock()
    issuer.dbid = dbid
    issuer.name = name
    issuer.addresses.all.return_value = addresses if addresses is not None else [
        _transactor_address()
    ]
    issuer.phones.all.return_value = phones if phones is not None else [
        _transactor_phone()
    ]
    return issuer


def _transactor_address(
    *,
    line1: str = "1 Health Way",
    city: str = "Boston",
    state_code: str = "MA",
    postal_code: str = "02101",
) -> MagicMock:
    addr = MagicMock()
    addr.line1 = line1
    addr.city = city
    addr.state_code = state_code
    addr.postal_code = postal_code
    return addr


def _transactor_phone(*, value: str = "617-555-0100") -> MagicMock:
    phone = MagicMock()
    phone.value = value
    return phone


def _patient_address(
    *,
    use: str = "home",
    type: str = "both",
    line1: str = "123 Main St",
    city: str = "Boston",
    state_code: str = "MA",
    postal_code: str = "02101",
) -> MagicMock:
    addr = MagicMock()
    addr.use = use
    addr.type = type
    addr.line1 = line1
    addr.city = city
    addr.state_code = state_code
    addr.postal_code = postal_code
    return addr


@pytest.fixture
def make_coverage():
    return _coverage


@pytest.fixture
def make_issuer():
    return _issuer


@pytest.fixture
def make_transactor_address():
    return _transactor_address


@pytest.fixture
def make_transactor_phone():
    return _transactor_phone


@pytest.fixture
def make_patient_address():
    return _patient_address


@pytest.fixture
def patient_with(make_coverage, make_patient_address):
    """Build a fully-mocked Patient with explicit coverages and addresses."""

    def _build(coverages: list | None = None, addresses: list | None = None) -> MagicMock:
        patient = MagicMock()
        patient.id = "patient-uuid"
        patient.coverages.all.return_value = coverages if coverages is not None else [
            make_coverage(rank=1, issuer=MagicMock(dbid=1, name="Acme Health"))
        ]
        patient.addresses.all.return_value = addresses if addresses is not None else [
            make_patient_address()
        ]
        return patient

    return _build


@pytest.fixture
def healthy_patient(patient_with, make_coverage, make_issuer, make_patient_address):
    """A patient that should pass all four rules."""
    issuer = make_issuer(dbid=42, name="Acme Health")
    return patient_with(
        coverages=[make_coverage(rank=1, issuer=issuer)],
        addresses=[make_patient_address()],
    )
