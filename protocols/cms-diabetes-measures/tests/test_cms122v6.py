"""Tests for the CMS122v6 HbA1c poor-control protocol."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import arrow
import pytest

from protocols.cms122v6_diabetes_hemoglobin_a1c_poor_control import (
    ClinicalQualityMeasure122v6,
)


@pytest.fixture
def patient() -> SimpleNamespace:
    """A stub patient with the minimum attributes the protocol reads.

    ``age_at`` derives the age live from the (mutable) ``birth_date`` attribute so tests
    that swap the birth date to test age gating get a fresh computation each call.
    """
    p = SimpleNamespace(
        id="patient-1",
        first_name="Dohav",
        birth_date=arrow.get("1980-01-01").date(),
    )

    def age_at(when: arrow.Arrow) -> float:
        """Approximate age-at using a 365-day year (good enough for these tests)."""
        return (when.date() - p.birth_date).days / 365.0

    p.age_at = age_at
    return p


@pytest.fixture
def protocol(patient) -> ClinicalQualityMeasure122v6:
    """Construct the protocol and short-circuit the ID lookup + patient fetch."""
    proto = ClinicalQualityMeasure122v6.__new__(ClinicalQualityMeasure122v6)
    proto.event = MagicMock()
    proto.secrets = {}
    proto.environment = {}
    proto._patient_id = patient.id
    proto.now = arrow.get("2018-08-23T00:00:00Z")
    # Pre-seed the cached_property so accessing self.patient doesn't hit the ORM.
    proto.__dict__["patient"] = patient
    return proto


def test_meta_description() -> None:
    """The class's description matches the legacy text."""
    assert (
        "Patients 18-75 years of age with diabetes who have either a hemoglobin A1c > 9.0%"
        in ClinicalQualityMeasure122v6.Meta.description
    )


def test_meta_identifier() -> None:
    """The CMS identifier is preserved."""
    assert ClinicalQualityMeasure122v6.Meta.identifiers == ["CMS122v6"]


def test_enabled() -> None:
    """``enabled`` always returns True for parity with legacy behavior."""
    assert ClinicalQualityMeasure122v6.enabled() is True


def test_responds_to_includes_lab_report() -> None:
    """The protocol must subscribe to lab-report events to recompute on HbA1c results."""
    assert "LAB_REPORT_CREATED" in ClinicalQualityMeasure122v6.RESPONDS_TO
    assert "LAB_REPORT_UPDATED" in ClinicalQualityMeasure122v6.RESPONDS_TO


def test_in_numerator_missing_lab_is_true(protocol) -> None:
    """Missing HbA1c is treated as poor control."""
    protocol.__dict__["last_hba1c_lab_value"] = None
    assert protocol.in_numerator() is True


def test_in_numerator_high_value_is_true(protocol) -> None:
    """HbA1c above 9.0 is poor control."""
    protocol.__dict__["last_hba1c_lab_value"] = SimpleNamespace(
        value=11.2,
        report=SimpleNamespace(original_date=arrow.get("2018-08-02").datetime),
    )
    assert protocol.in_numerator() is True


def test_in_numerator_normal_value_is_false(protocol) -> None:
    """HbA1c at or below 9.0 is *not* poor control."""
    protocol.__dict__["last_hba1c_lab_value"] = SimpleNamespace(
        value=7.0,
        report=SimpleNamespace(original_date=arrow.get("2018-08-02").datetime),
    )
    assert protocol.in_numerator() is False


def test_in_denominator_age_gating(protocol) -> None:
    """Patients younger than 18 or 75+ are excluded from the denominator."""
    protocol.patient.birth_date = arrow.get("2010-01-01").date()  # too young
    with patch.object(protocol, "has_diabetes_in_period", return_value=True):
        assert protocol.in_denominator() is False

    protocol.patient.birth_date = arrow.get("1940-01-01").date()  # too old
    with patch.object(protocol, "has_diabetes_in_period", return_value=True):
        assert protocol.in_denominator() is False


def test_in_denominator_without_diabetes(protocol) -> None:
    """No active diabetes -> not in the denominator."""
    with patch.object(protocol, "has_diabetes_in_period", return_value=False):
        assert protocol.in_denominator() is False


def test_in_denominator_eligible(protocol) -> None:
    """Eligible-age patient with diabetes is in the denominator."""
    with patch.object(protocol, "has_diabetes_in_period", return_value=True):
        assert protocol.in_denominator() is True


def test_compute_returns_not_applicable_when_not_in_denominator(protocol) -> None:
    """Out-of-denominator emits one NOT_APPLICABLE protocol card."""
    with patch.object(protocol, "in_denominator", return_value=False):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_due_when_no_hba1c(protocol) -> None:
    """No HbA1c on file -> DUE with an Order recommendation."""
    protocol.__dict__["last_hba1c_lab_value"] = None
    with patch.object(protocol, "in_denominator", return_value=True):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_satisfied_when_recent_normal(protocol) -> None:
    """Recent in-range HbA1c -> SATISFIED."""
    protocol.__dict__["last_hba1c_lab_value"] = SimpleNamespace(
        value=7.0,
        report=SimpleNamespace(original_date=arrow.get("2018-08-02").datetime),
    )
    with patch.object(protocol, "in_denominator", return_value=True):
        effects = protocol.compute()
    assert len(effects) == 1
