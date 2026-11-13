"""CMS125v15 breast cancer screening, against real records."""

from __future__ import annotations

import hashlib
from pathlib import Path

import arrow
import pytest
from canvas_sdk.value_set.v2027.condition import HospiceDiagnosis, StatusPostRightMastectomy
from canvas_sdk.value_set.v2027.diagnostic_study import Mammography
from canvas_sdk.value_set.v2027.encounter import OfficeVisit
from canvas_sdk.value_set.v2027.procedure import BilateralMastectomy, UnilateralMastectomyLeft

from protocols.cms125v6_breast_cancer_screening import ClinicalQualityMeasure125v6

from . import records

MAMMOGRAM = sorted(Mammography.LOINC)[0]
PROTOCOLS = Path(__file__).parents[2]


def first(value_set, system: str) -> str:  # noqa: ANN001
    return sorted(getattr(value_set, system))[0]


def eligible(birth_date: str = "1970-01-01", sex: str = "F"):  # noqa: ANN201
    """A patient with an office visit in the measurement period."""
    who = records.patient(birth_date, sex)
    records.visit(who, first(OfficeVisit, "CPT"), "2027-01-10")
    return who


def status(who) -> str:  # noqa: ANN001
    return records.card(records.build(ClinicalQualityMeasure125v6, who).compute())["status"]


def test_meta_identifies_v15() -> None:
    """The measure reports the 2027 version."""
    assert ClinicalQualityMeasure125v6.Meta.identifiers == ["CMS125v15"]


@pytest.mark.parametrize(
    ("birth_date", "applies"),
    [("1985-06-15", True), ("1985-06-16", False), ("1952-06-16", True), ("1952-06-15", False)],
)
def test_age_range_is_42_to_74(birth_date: str, applies: bool) -> None:
    """42 and 74 at the end of the period are in; 41 and 75 are out."""
    protocol = records.build(ClinicalQualityMeasure125v6, eligible(birth_date))
    assert protocol.in_initial_population() is applies


def test_men_are_not_in_the_population() -> None:
    """The measure covers women only."""
    assert not records.build(ClinicalQualityMeasure125v6, eligible(sex="M")).in_initial_population()


def test_requires_a_qualifying_visit() -> None:
    """A woman with no qualifying visit in the period is not in the population."""
    assert not records.build(ClinicalQualityMeasure125v6, records.patient()).in_initial_population()


def test_mammogram_within_27_months_satisfies() -> None:
    """A mammogram 20 months before the end of the period satisfies."""
    who = eligible()
    records.imaging_report(who, records.LOINC, MAMMOGRAM, "2025-10-20")
    assert status(who) == "satisfied"


def test_mammogram_older_than_27_months_is_due() -> None:
    """A mammogram 28 months before the end of the period does not satisfy."""
    who = eligible()
    records.imaging_report(who, records.LOINC, MAMMOGRAM, "2025-02-15")
    assert status(who) == "due"


def test_bilateral_mastectomy_excludes() -> None:
    """A bilateral mastectomy procedure takes the patient out of the denominator."""
    who = eligible()
    records.procedure(who, records.SNOMEDCT, first(BilateralMastectomy, "SNOMEDCT"), "2015-01-01")
    assert status(who) == "not_applicable"


def test_both_sides_exclude_but_one_side_does_not() -> None:
    """A right status-post diagnosis plus a left mastectomy excludes; the right side alone does not."""
    both, right_only = eligible(), eligible()
    for who in (both, right_only):
        records.condition(who, records.ICD10, first(StatusPostRightMastectomy, "ICD10CM"))
    records.procedure(both, records.SNOMEDCT, first(UnilateralMastectomyLeft, "SNOMEDCT"), "2018-01-01")
    assert status(both) == "not_applicable"
    assert status(right_only) == "due"


def test_hospice_excludes() -> None:
    """The shared hospice exclusion applies."""
    who = eligible()
    records.condition(who, records.SNOMEDCT, first(HospiceDiagnosis, "SNOMEDCT"))
    assert status(who) == "not_applicable"


def test_first_due_in_counts_down_to_42() -> None:
    """A 40-year-old woman's card says when she reaches 42."""
    protocol = records.build(ClinicalQualityMeasure125v6, eligible("1987-06-15"))
    assert protocol.first_due_in() == (arrow.get("2029-06-15") - protocol.timeframe.end).days


def test_ecqm_common_matches_the_other_plugins() -> None:
    """This plugin's copy of the shared module matches every other copy."""
    copies = sorted(PROTOCOLS.glob("*/protocols/ecqm_common.py"))
    assert len({hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}) == 1
