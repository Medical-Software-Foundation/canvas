"""Tests for the CMS123v6 diabetic foot-exam protocol."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import arrow
import pytest

from protocols.cms123v6_diabetes_foot_exam import (
    BilateralAmputationOfLegBelowOrAboveKnee,
    ClinicalQualityMeasure123v6,
    PulseExamOfFoot,
    SensoryExamOfFoot,
    VisualExamOfFoot,
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
def protocol(patient) -> ClinicalQualityMeasure123v6:
    """Bypass __init__ so we don't need a real Event or DB lookup."""
    proto = ClinicalQualityMeasure123v6.__new__(ClinicalQualityMeasure123v6)
    proto.event = MagicMock()
    proto.secrets = {}
    proto.environment = {}
    proto._patient_id = patient.id
    proto.now = arrow.get("2018-08-23T00:00:00Z")
    proto.__dict__["patient"] = patient
    return proto


def test_meta_description_and_identifier() -> None:
    """Manifest metadata is preserved."""
    assert (
        "Patients 18-75 years of age with diabetes who have not received a foot exam"
        in ClinicalQualityMeasure123v6.Meta.description
    )
    assert ClinicalQualityMeasure123v6.Meta.identifiers == ["CMS123v6"]


def test_foot_exam_value_sets_have_snomed_codes() -> None:
    """All three foot-exam findings preserve their SNOMED codes verbatim."""
    assert VisualExamOfFoot.SNOMEDCT == {"401191002"}
    assert SensoryExamOfFoot.SNOMEDCT == {"134388005"}
    assert PulseExamOfFoot.SNOMEDCT == {"91161007"}


def test_amputation_value_set_keeps_icd_codes() -> None:
    """Bilateral-amputation exclusion value set retains its ICD-10 codes."""
    assert "Q7203" in BilateralAmputationOfLegBelowOrAboveKnee.ICD10CM
    assert "Q7223" in BilateralAmputationOfLegBelowOrAboveKnee.ICD10CM


def test_period_handles_empty_and_single_and_range(protocol) -> None:
    """Period text varies based on the number/spread of exam dates."""
    protocol._on_dates = None
    assert protocol.period == "N/A"

    protocol._on_dates = [arrow.get("2018-08-23"), arrow.get("2018-08-23")]
    assert "on 8/23/18" in protocol.period

    protocol._on_dates = [arrow.get("2018-08-21"), arrow.get("2018-08-23")]
    assert protocol.period == "between 8/21/18 and 8/23/18"


def test_in_numerator_requires_all_three_findings(protocol) -> None:
    """Missing any one of visual/sensory/pulse fails the numerator."""
    with patch.object(protocol, "_exam_dates", return_value=[arrow.get("2018-08-01")]):
        assert protocol.in_numerator() is True

    def only_visual(value_set):  # noqa: ANN001
        return [arrow.get("2018-08-01")] if value_set is VisualExamOfFoot else []

    with patch.object(protocol, "_exam_dates", side_effect=only_visual):
        assert protocol.in_numerator() is False


def test_compute_not_applicable_when_no_diabetes(protocol) -> None:
    """Out-of-denominator -> NOT_APPLICABLE."""
    with patch.object(protocol, "in_denominator", return_value=False):
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_due_when_exam_missing(protocol) -> None:
    """In denominator + missing exam -> DUE."""
    with (
        patch.object(protocol, "in_denominator", return_value=True),
        patch.object(protocol, "in_numerator", return_value=False),
    ):
        protocol._on_dates = []
        effects = protocol.compute()
    assert len(effects) == 1


def test_compute_satisfied_when_exam_complete(protocol) -> None:
    """All three findings within the period -> SATISFIED."""
    with (
        patch.object(protocol, "in_denominator", return_value=True),
        patch.object(protocol, "in_numerator", return_value=True),
    ):
        protocol._on_dates = [arrow.get("2018-08-22")]
        effects = protocol.compute()
    assert len(effects) == 1
