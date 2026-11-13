"""CMS122v15 glycemic status assessment, against real records."""

from __future__ import annotations

import pytest
from canvas_sdk.value_set.v2027.condition import Diabetes, HospiceDiagnosis
from canvas_sdk.value_set.v2027.encounter import OfficeVisit
from canvas_sdk.value_set.v2027.laboratory_test import Hba1cLaboratoryTest

from protocols.cms122v6_diabetes_hemoglobin_a1c_poor_control import (
    GLUCOSE_MANAGEMENT_INDICATOR,
    ClinicalQualityMeasure122v6,
)

from . import records

HBA1C = sorted(Hba1cLaboratoryTest.LOINC)[0]


def eligible(birth_date: str = "1970-01-01"):  # noqa: ANN201
    """A patient with diabetes and an office visit in the measurement period."""
    who = records.patient(birth_date)
    records.condition(who, records.ICD10, sorted(Diabetes.ICD10CM)[0])
    records.visit(who, sorted(OfficeVisit.CPT)[0], "2027-01-10")
    return who


def status(who) -> str:  # noqa: ANN001
    return records.card(records.build(ClinicalQualityMeasure122v6, who).compute())["status"]


def test_meta_identifies_v15() -> None:
    """The measure reports the 2027 version."""
    assert ClinicalQualityMeasure122v6.Meta.identifiers == ["CMS122v15"]


@pytest.mark.parametrize(("birth_date", "applies"), [("1951-06-16", True), ("1951-06-15", False)])
def test_age_range_includes_75(birth_date: str, applies: bool) -> None:
    """75 at the end of the period is in; 76 is out."""
    protocol = records.build(ClinicalQualityMeasure122v6, eligible(birth_date))
    assert protocol.in_initial_population() is applies


def test_requires_a_qualifying_visit() -> None:
    """Diabetes without a qualifying visit in the period is not in the population."""
    who = records.patient()
    records.condition(who, records.ICD10, sorted(Diabetes.ICD10CM)[0])
    assert not records.build(ClinicalQualityMeasure122v6, who).in_initial_population()


def test_hospice_excludes() -> None:
    """A hospice diagnosis takes the patient out of the denominator."""
    who = eligible()
    records.condition(who, records.SNOMEDCT, sorted(HospiceDiagnosis.SNOMEDCT)[0])
    assert status(who) == "not_applicable"


def test_no_assessment_is_poor_control() -> None:
    """No HbA1c or GMI in the period counts as poor control."""
    assert status(eligible()) == "due"


@pytest.mark.parametrize(("value", "expected"), [("9.1", "due"), ("9.0", "satisfied"), ("6.8", "satisfied")])
def test_threshold(value: str, expected: str) -> None:
    """Above 9.0% is poor control; 9.0% and below is not."""
    who = eligible()
    records.lab(who, records.LOINC, HBA1C, value, "2027-03-01")
    assert status(who) == expected


def test_glucose_management_indicator_counts() -> None:
    """A GMI result is a glycemic status assessment."""
    who = eligible()
    records.lab(who, records.LOINC, GLUCOSE_MANAGEMENT_INDICATOR, "7.1", "2027-03-01")
    assert status(who) == "satisfied"


def test_numeric_result_wins_over_a_more_recent_one_without_a_value() -> None:
    """v15 prefers a numeric result even when a result without a value is more recent."""
    who = eligible()
    records.lab(who, records.LOINC, HBA1C, "7.0", "2027-02-01")
    records.lab(who, records.LOINC, HBA1C, "see comment", "2027-05-01")
    assert status(who) == "satisfied"


def test_only_results_without_a_value_is_poor_control() -> None:
    """When every result lacks a value, the measure counts poor control."""
    who = eligible()
    records.lab(who, records.LOINC, HBA1C, "see comment", "2027-05-01")
    assert status(who) == "due"


def test_lowest_result_on_the_most_recent_day_counts() -> None:
    """Two results on the most recent day: the lower one decides."""
    who = eligible()
    records.lab(who, records.LOINC, HBA1C, "11.0", "2027-01-01")
    records.lab(who, records.LOINC, HBA1C, "9.5", "2027-04-01")
    records.lab(who, records.LOINC, GLUCOSE_MANAGEMENT_INDICATOR, "8.2", "2027-04-01")
    assert status(who) == "satisfied"


def test_result_before_the_period_does_not_count() -> None:
    """A controlled result older than the period leaves the patient in poor control."""
    who = eligible()
    records.lab(who, records.LOINC, HBA1C, "6.0", "2026-01-01")
    assert status(who) == "due"
