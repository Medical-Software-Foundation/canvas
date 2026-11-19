"""Shared test fixtures for the medication_history plugin."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

FDB_SYSTEM = "http://www.fdbhealth.com/"
RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"
NDC_SYSTEM = "http://hl7.org/fhir/sid/ndc"


@pytest.fixture
def mock_event():
    """Event whose target is a patient with a known id."""
    event = MagicMock()
    event.target.id = "patient-123"
    return event


@pytest.fixture
def mock_patient():
    """A patient with a name used in the modal header."""
    patient = MagicMock()
    patient.first_name = "Jane"
    patient.last_name = "Doe"
    return patient


def make_coding(system, display, code=""):
    """A Medication coding-like object."""
    return SimpleNamespace(system=system, display=display, code=code)


def make_medication(codings=None, **overrides):
    """Build a Medication-like object for formatter tests.

    Uses SimpleNamespace so attribute access returns real values, and exposes
    a `.codings.all()` callable matching the ORM relationship API.
    """
    if codings is None:
        codings = [make_coding(FDB_SYSTEM, "ADVAIR 100-50 DISKUS")]
    defaults = dict(
        status="active",
        start_date=datetime(2019, 9, 4),
        end_date=None,
        clinical_quantity_description="1 inhaler",
        national_drug_code="00173-0696-00",
    )
    defaults.update(overrides)
    med = SimpleNamespace(**defaults)
    med.codings = SimpleNamespace(all=lambda: codings)
    return med
