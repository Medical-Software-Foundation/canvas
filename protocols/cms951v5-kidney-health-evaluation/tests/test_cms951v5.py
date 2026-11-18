"""CMS951v5 kidney health evaluation, against real records."""

from __future__ import annotations

import pytest
from canvas_sdk.value_set.v2027.condition import ChronicKidneyDiseaseStage5, Diabetes
from canvas_sdk.value_set.v2027.encounter import OfficeVisit
from canvas_sdk.value_set.v2027.laboratory_test import (
    EstimatedGlomerularFiltrationRate,
    UrineAlbumin,
    UrineAlbuminCreatinineRatio,
    UrineCreatinine,
)

from protocols.cms951v5_kidney_health_evaluation import ClinicalQualityMeasure951v5

from . import records


def loinc(value_set) -> str:  # noqa: ANN001
    return sorted(value_set.LOINC)[0]


def eligible(birth_date: str = "1960-01-01", diabetes_onset: str = "2020-01-01"):  # noqa: ANN201
    """A patient with diabetes since before the period and an office visit during it."""
    who = records.patient(birth_date)
    records.condition(who, records.ICD10, sorted(Diabetes.ICD10CM)[0], onset=diabetes_onset)
    records.visit(who, sorted(OfficeVisit.CPT)[0], "2027-01-10")
    return who


def status(who) -> str:  # noqa: ANN001
    return records.card(records.build(ClinicalQualityMeasure951v5, who).compute())["status"]


def test_registered_in_the_manifest() -> None:
    """The bundle ships CMS951 in place of the retired CMS134."""
    assert ClinicalQualityMeasure951v5.Meta.identifiers == ["CMS951v5"]


@pytest.mark.parametrize(("birth_date", "applies"), [("1941-06-15", True), ("1940-06-15", False)])
def test_age_range_is_18_to_85_at_the_start(birth_date: str, applies: bool) -> None:
    """85 at the start of the period is in; 86 is out."""
    protocol = records.build(ClinicalQualityMeasure951v5, eligible(birth_date))
    assert protocol.in_initial_population() is applies


def test_diabetes_diagnosed_during_the_period_is_not_in_the_population() -> None:
    """Diabetes must already be active when the period starts."""
    protocol = records.build(ClinicalQualityMeasure951v5, eligible(diabetes_onset="2027-01-01"))
    assert not protocol.in_initial_population()


def test_ckd_stage_5_excludes() -> None:
    """Chronic kidney disease stage 5 takes the patient out of the denominator."""
    who = eligible()
    records.condition(who, records.ICD10, sorted(ChronicKidneyDiseaseStage5.ICD10CM)[0])
    assert status(who) == "not_applicable"


def test_egfr_alone_is_due() -> None:
    """An eGFR without a urine albumin-creatinine ratio does not satisfy."""
    who = eligible()
    records.lab(who, records.LOINC, loinc(EstimatedGlomerularFiltrationRate), "72", "2027-02-01")
    assert status(who) == "due"


def test_egfr_and_uacr_satisfy() -> None:
    """An eGFR and a uACR in the period satisfy."""
    who = eligible()
    records.lab(who, records.LOINC, loinc(EstimatedGlomerularFiltrationRate), "72", "2027-02-01")
    records.lab(who, records.LOINC, loinc(UrineAlbuminCreatinineRatio), "<30", "2027-02-01")
    assert status(who) == "satisfied"


@pytest.mark.parametrize(("creatinine_date", "expected"), [("2027-02-05", "satisfied"), ("2027-02-06", "due")])
def test_urine_albumin_and_creatinine_within_four_days(creatinine_date: str, expected: str) -> None:
    """A urine albumin and creatinine at most four days apart stand in for the uACR."""
    who = eligible()
    records.lab(who, records.LOINC, loinc(EstimatedGlomerularFiltrationRate), "72", "2027-02-01")
    records.lab(who, records.LOINC, loinc(UrineAlbumin), "12", "2027-02-01")
    records.lab(who, records.LOINC, loinc(UrineCreatinine), "110", creatinine_date)
    assert status(who) == expected


def test_result_without_a_value_does_not_count() -> None:
    """A uACR with no numeric value is not a resulted test."""
    who = eligible()
    records.lab(who, records.LOINC, loinc(EstimatedGlomerularFiltrationRate), "72", "2027-02-01")
    records.lab(who, records.LOINC, loinc(UrineAlbuminCreatinineRatio), "pending", "2027-02-01")
    assert status(who) == "due"
