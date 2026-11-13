"""CMS138v15 tobacco screening and cessation intervention, against real records."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from canvas_sdk.value_set.v2027.assessment import TobaccoUseScreening
from canvas_sdk.value_set.v2027.condition import HospiceDiagnosis
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    OfficeVisit,
    TelephoneVisits,
)
from canvas_sdk.value_set.v2027.intervention import TobaccoUseCessationCounseling
from canvas_sdk.value_set.v2027.medication import TobaccoUseCessationPharmacotherapy
from canvas_sdk.value_set.v2027.no_qdm_category_assigned import TobaccoNonUser, TobaccoUser

from protocols.cms138v6_tobacco_screening_and_cessation import ClinicalQualityMeasure138v6

from . import records

PROTOCOLS = Path(__file__).parents[2]
SCREENING = sorted(TobaccoUseScreening.LOINC)[0]
USER = sorted(TobaccoUser.SNOMEDCT)[0]
NON_USER = sorted(TobaccoNonUser.SNOMEDCT)[0]


def first(value_set, system: str) -> str:  # noqa: ANN001
    return sorted(getattr(value_set, system))[0]


def eligible(birth_date: str = "1980-01-01"):  # noqa: ANN201
    """A patient with an annual wellness visit (a preventive visit) in the period."""
    who = records.patient(birth_date)
    records.visit(who, first(AnnualWellnessVisit, "HCPCSLEVELII"), "2027-01-10")
    return who


def screen(who, result: str, when: str) -> None:  # noqa: ANN001
    records.questionnaire_answer(who, SCREENING, "72166-2", result, when)


def card(who) -> dict:  # noqa: ANN001
    return records.card(records.build(ClinicalQualityMeasure138v6, who).compute())


def test_meta_identifies_v15() -> None:
    """The measure reports the 2027 version."""
    assert ClinicalQualityMeasure138v6.Meta.identifiers == ["CMS138v15"]


@pytest.mark.parametrize(("birth_date", "applies"), [("2014-06-15", True), ("2014-06-16", False)])
def test_patients_12_and_older_at_the_start(birth_date: str, applies: bool) -> None:
    """12 at the start of the period is in; 11 is out."""
    protocol = records.build(ClinicalQualityMeasure138v6, eligible(birth_date))
    assert protocol.in_initial_population() is applies


def test_two_qualifying_visits_or_one_preventive_visit() -> None:
    """Two non-preventive visits qualify; one does not."""
    one, two = records.patient(), records.patient()
    records.visit(one, first(OfficeVisit, "CPT"), "2027-01-10")
    records.visit(two, first(OfficeVisit, "CPT"), "2027-01-10")
    records.visit(two, first(TelephoneVisits, "CPT"), "2027-03-10")
    assert not records.build(ClinicalQualityMeasure138v6, one).in_initial_population()
    assert records.build(ClinicalQualityMeasure138v6, two).in_initial_population()


def test_unscreened_patient_is_due_for_screening() -> None:
    """No screening in the period: screen for tobacco use."""
    result = card(eligible())
    assert result["status"] == "due"
    assert "screened" in result["narrative"]


def test_screening_counts_only_within_the_period() -> None:
    """A screening from 13 months ago leaves the patient due for screening."""
    who = eligible()
    screen(who, NON_USER, "2026-05-01")
    assert "screened" in card(who)["narrative"]


def test_non_user_is_satisfied() -> None:
    """A non-user screening in the period satisfies."""
    who = eligible()
    screen(who, NON_USER, "2027-02-01")
    assert card(who)["status"] == "satisfied"


def test_most_recent_screening_decides_status() -> None:
    """A non-user screening after a user screening makes the patient a non-user."""
    who = eligible()
    screen(who, USER, "2026-08-01")
    screen(who, NON_USER, "2027-02-01")
    assert card(who)["status"] == "satisfied"


def test_user_without_intervention_is_due() -> None:
    """A tobacco user without counseling or medication needs an intervention."""
    who = eligible()
    screen(who, USER, "2027-02-01")
    result = card(who)
    assert result["status"] == "due"
    assert "intervention is indicated" in result["narrative"]


def test_counseling_before_the_screening_counts() -> None:
    """v15 counts counseling in the six months before the period, before the screening."""
    who = eligible()
    records.instruction(
        who, records.SNOMEDCT, first(TobaccoUseCessationCounseling, "SNOMEDCT"), "2026-02-01"
    )
    screen(who, USER, "2027-02-01")
    assert card(who)["status"] == "satisfied"


def test_counseling_earlier_than_six_months_before_does_not_count() -> None:
    """Counseling more than six months before the period does not count."""
    who = eligible()
    records.instruction(
        who, records.SNOMEDCT, first(TobaccoUseCessationCounseling, "SNOMEDCT"), "2025-11-01"
    )
    screen(who, USER, "2027-02-01")
    assert card(who)["status"] == "due"


def test_tobacco_abuse_counseling_diagnosis_counts() -> None:
    """A Z71.6 diagnosis starting in the window is counseling."""
    who = eligible()
    records.condition(who, records.ICD10, "Z716", onset="2027-03-01")
    screen(who, USER, "2027-02-01")
    assert card(who)["status"] == "satisfied"


def test_cessation_medication_counts() -> None:
    """A cessation medication started in the window is an intervention."""
    who = eligible()
    records.medication(who, first(TobaccoUseCessationPharmacotherapy, "RXNORM"), "2027-03-01")
    screen(who, USER, "2027-02-01")
    assert card(who)["status"] == "satisfied"


def test_hospice_excludes() -> None:
    """Patients in hospice are excluded."""
    who = eligible()
    records.condition(who, records.SNOMEDCT, first(HospiceDiagnosis, "SNOMEDCT"))
    assert card(who)["status"] == "not_applicable"


def test_ecqm_common_matches_the_other_plugins() -> None:
    """This plugin's copy of the shared module matches every other copy."""
    copies = sorted(PROTOCOLS.glob("*/protocols/ecqm_common.py"))
    assert len({hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}) == 1
