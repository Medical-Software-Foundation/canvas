"""CMS130v15 colorectal cancer screening, against real records."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from canvas_sdk.value_set.v2027.condition import HospiceDiagnosis, MalignantNeoplasmOfColon
from canvas_sdk.value_set.v2027.diagnostic_study import CtColonography
from canvas_sdk.value_set.v2027.encounter import OfficeVisit
from canvas_sdk.value_set.v2027.laboratory_test import FecalOccultBloodTestFobt, SdnaFitTest
from canvas_sdk.value_set.v2027.procedure import Colonoscopy, TotalColectomy

from protocols.cms130v6_colorectal_cancer_screening import ClinicalQualityMeasure130v6

from . import records

PROTOCOLS = Path(__file__).parents[2]


def first(value_set, system: str) -> str:  # noqa: ANN001
    return sorted(getattr(value_set, system))[0]


def eligible(birth_date: str = "1970-01-01"):  # noqa: ANN201
    """A patient with an office visit in the measurement period."""
    who = records.patient(birth_date)
    records.visit(who, first(OfficeVisit, "CPT"), "2027-01-10")
    return who


def card(who) -> dict:  # noqa: ANN001
    return records.card(records.build(ClinicalQualityMeasure130v6, who).compute())


def test_meta_identifies_v15() -> None:
    """The measure reports the 2027 version."""
    assert ClinicalQualityMeasure130v6.Meta.identifiers == ["CMS130v15"]


@pytest.mark.parametrize(
    ("birth_date", "applies"),
    [("1981-06-15", True), ("1981-06-16", False), ("1951-06-16", True), ("1951-06-15", False)],
)
def test_age_range_is_46_to_75(birth_date: str, applies: bool) -> None:
    """46 and 75 at the end of the period are in; 45 and 76 are out."""
    protocol = records.build(ClinicalQualityMeasure130v6, eligible(birth_date))
    assert protocol.in_initial_population() is applies


def test_no_screening_is_due() -> None:
    """Without a screening the patient is due."""
    assert card(eligible())["status"] == "due"


@pytest.mark.parametrize(("when", "expected"), [("2026-07-01", "satisfied"), ("2026-05-01", "due")])
def test_fobt_counts_only_in_the_period(when: str, expected: str) -> None:
    """An FOBT with any result counts during the period, not before it."""
    who = eligible()
    records.lab(who, records.LOINC, first(FecalOccultBloodTestFobt, "LOINC"), "Negative", when)
    assert card(who)["status"] == expected


@pytest.mark.parametrize(("when", "expected"), [("2024-07-01", "satisfied"), ("2024-05-01", "due")])
def test_sdna_fit_counts_for_two_years_before(when: str, expected: str) -> None:
    """An sDNA FIT test counts during the period or the two years before it."""
    who = eligible()
    records.lab(who, records.LOINC, first(SdnaFitTest, "LOINC"), "Negative", when)
    assert card(who)["status"] == expected


def test_lab_without_a_result_does_not_count() -> None:
    """An FOBT with no result value does not count."""
    who = eligible()
    records.lab(who, records.LOINC, first(FecalOccultBloodTestFobt, "LOINC"), "", "2027-01-01")
    assert card(who)["status"] == "due"


@pytest.mark.parametrize(("when", "expected"), [("2017-07-01", "satisfied"), ("2017-05-01", "due")])
def test_colonoscopy_counts_for_nine_years_before(when: str, expected: str) -> None:
    """A colonoscopy referral report counts during the period or the nine years before it."""
    who = eligible()
    records.referral_report(who, records.SNOMEDCT, first(Colonoscopy, "SNOMEDCT"), when)
    assert card(who)["status"] == expected


def test_ct_colonography_imaging_report_counts() -> None:
    """A CT colonography imaging report in the window satisfies."""
    who = eligible()
    records.imaging_report(who, records.LOINC, first(CtColonography, "LOINC"), "2024-01-01")
    assert card(who)["status"] == "satisfied"


def test_card_reports_the_screening_that_lasts_longest() -> None:
    """A recent FOBT and an older colonoscopy: the colonoscopy sets when screening is next due."""
    who = eligible()
    records.lab(who, records.LOINC, first(FecalOccultBloodTestFobt, "LOINC"), "Negative", "2027-05-01")
    records.procedure(who, records.SNOMEDCT, first(Colonoscopy, "SNOMEDCT"), "2022-06-15")
    assert "colonoscopy" in card(who)["narrative"]


def test_resolved_colon_cancer_still_excludes() -> None:
    """A history of colorectal cancer excludes even after it resolves."""
    who = eligible()
    records.condition(
        who, records.ICD10, first(MalignantNeoplasmOfColon, "ICD10CM"), onset="2015-01-01", resolved="2016-01-01"
    )
    assert card(who)["status"] == "not_applicable"


def test_total_colectomy_excludes() -> None:
    """A total colectomy procedure excludes."""
    who = eligible()
    records.procedure(who, records.SNOMEDCT, first(TotalColectomy, "SNOMEDCT"), "2010-01-01")
    assert card(who)["status"] == "not_applicable"


def test_hospice_excludes() -> None:
    """The shared hospice exclusion applies."""
    who = eligible()
    records.condition(who, records.SNOMEDCT, first(HospiceDiagnosis, "SNOMEDCT"))
    assert card(who)["status"] == "not_applicable"


def test_ecqm_common_matches_the_other_plugins() -> None:
    """This plugin's copy of the shared module matches every other copy."""
    copies = sorted(PROTOCOLS.glob("*/protocols/ecqm_common.py"))
    assert len({hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}) == 1
