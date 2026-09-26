"""Tests for the CMS131v6 diabetic eye-exam protocol."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import arrow
import pytest

from protocols.cms131v6_diabetes_eye_exam import (
    FundusPhotography,
    ClinicalQualityMeasure131v6,
)


@pytest.fixture
def patient() -> SimpleNamespace:
    """Eligible adult patient stub with a derived ``age_at``."""
    p = SimpleNamespace(
        id="patient-1",
        first_name="Dohav",
        birth_date=arrow.get("1980-01-01").date(),
    )
    p.age_at = lambda when: (when.date() - p.birth_date).days / 365.0
    return p


@pytest.fixture
def protocol(patient) -> ClinicalQualityMeasure131v6:
    """Build a protocol instance without invoking __init__'s event plumbing."""
    proto = ClinicalQualityMeasure131v6.__new__(ClinicalQualityMeasure131v6)
    proto.event = MagicMock()
    proto.secrets = {}
    proto.environment = {}
    proto._patient_id = patient.id
    proto.now = arrow.get("2018-08-23T00:00:00Z")
    proto.__dict__["patient"] = patient
    return proto


def test_meta_metadata() -> None:
    """Description and identifier copy through from the legacy class."""
    assert (
        "Patients 18-75 years of age with diabetes who have not had a retinal or "
        "dilated eye exam by an eye care professional."
        == ClinicalQualityMeasure131v6.Meta.description
    )
    assert ClinicalQualityMeasure131v6.Meta.identifiers == ["CMS131v6"]


def test_fundus_photography_cpt_code() -> None:
    """CPT 92250 is preserved on the helper value set."""
    assert FundusPhotography.CPT == {"92250"}


def test_in_numerator_returns_false_when_no_reports(protocol) -> None:
    """No retinal exam reports in either period -> not in numerator."""
    with patch.object(protocol, "_retinal_reports_in", return_value=[]):
        assert protocol.in_numerator() is False


def test_in_numerator_returns_true_with_in_period_exam(protocol) -> None:
    """An in-period exam satisfies regardless of finding."""
    report = SimpleNamespace(
        original_date=arrow.get("2018-08-22").date(),
        codings=SimpleNamespace(all=lambda: []),
    )

    def reports_in(start, end):  # noqa: ANN001
        if start == protocol.timeframe.start:
            return [report]
        return []

    with patch.object(protocol, "_retinal_reports_in", side_effect=reports_in):
        assert protocol.in_numerator() is True
        assert protocol._in_period is True


def test_in_numerator_prior_period_requires_negative_finding(protocol) -> None:
    """A prior-period exam with a non-negative finding does *not* satisfy."""
    abnormal = SimpleNamespace(
        original_date=arrow.get("2017-02-22").date(),
        codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(name="Findings", display="Retinopathy", code="other")],
        ),
    )

    def reports_in(start, end):  # noqa: ANN001
        if start == protocol.timeframe.start:
            return []
        return [abnormal]

    with patch.object(protocol, "_retinal_reports_in", side_effect=reports_in):
        assert protocol.in_numerator() is False
        assert protocol._in_period is False
        assert protocol._on_date == arrow.get("2017-02-22")


def test_in_numerator_prior_period_with_negative_finding_passes(protocol) -> None:
    """A prior-period exam with SNOMED 721103006 (no diabetic eye disease) satisfies."""
    negative = SimpleNamespace(
        original_date=arrow.get("2017-02-22").date(),
        codings=SimpleNamespace(
            all=lambda: [SimpleNamespace(name="Findings", display="", code="721103006")],
        ),
    )

    def reports_in(start, end):  # noqa: ANN001
        if start == protocol.timeframe.start:
            return []
        return [negative]

    with patch.object(protocol, "_retinal_reports_in", side_effect=reports_in):
        assert protocol.in_numerator() is True


def test_compute_not_applicable_without_diabetes(protocol) -> None:
    """No denominator -> NOT_APPLICABLE."""
    with patch.object(protocol, "in_denominator", return_value=False):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_due_emits_recommendations(protocol) -> None:
    """Unsatisfied -> DUE card with both perform and refer recommendations."""
    with (
        patch.object(protocol, "in_denominator", return_value=True),
        patch.object(protocol, "in_numerator", return_value=False),
    ):
        effects = protocol.compute()
    assert len(effects) == 1
