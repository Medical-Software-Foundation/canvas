"""The shared eCQM data access and exclusions, against real records."""

from __future__ import annotations

import hashlib
from pathlib import Path

import arrow
import pytest
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.value_set.v2027.condition import (
    AdvancedIllness,
    Diabetes,
    FrailtyDiagnosis,
    HospiceDiagnosis,
    PalliativeCareDiagnosis,
)
from canvas_sdk.value_set.v2027.encounter import HospiceEncounter, OfficeVisit
from canvas_sdk.value_set.v2027.intervention import HospiceCareAmbulatory
from canvas_sdk.value_set.v2027.medication import DementiaMedications
from canvas_sdk.value_set.value_set import ValueSet

from protocols.ecqm_common import (
    HOUSING_STATUS,
    LIVES_IN_NURSING_HOME,
    EcqmPatient,
    billing_codes,
    parse_number,
)

from . import records

PERIOD = Timeframe(start=arrow.get("2026-06-15"), end=arrow.get("2027-06-15"))
PROTOCOLS = Path(__file__).parents[2]


def first(value_set: type[ValueSet], system: str) -> str:
    """A stable code from one of a value set's code systems."""
    return sorted(getattr(value_set, system))[0]


def ecqm(who, age: int = 70) -> EcqmPatient:  # noqa: ANN001
    return EcqmPatient(who.id, PERIOD, age)


def test_condition_overlap_uses_onset_and_resolution() -> None:
    """A diagnosis counts when its prevalence period overlaps the window."""
    code = first(Diabetes, "ICD10CM")
    current, resolved_before, starts_after = (records.patient() for _ in range(3))
    records.condition(current, records.ICD10, code, onset="2019-01-01")
    records.condition(resolved_before, records.ICD10, code, onset="2019-01-01", resolved="2026-01-01")
    records.condition(starts_after, records.ICD10, code, onset="2027-07-01")
    assert ecqm(current).has_condition(Diabetes, PERIOD)
    assert not ecqm(resolved_before).has_condition(Diabetes, PERIOD)
    assert not ecqm(starts_after).has_condition(Diabetes, PERIOD)


def test_billing_codes_include_cpt_and_hcpcs() -> None:
    """Encounter matching reads CPT and HCPCS codes, which ``BillingLineItem.find`` ignores."""
    assert billing_codes(HospiceEncounter) == HospiceEncounter.HCPCSLEVELII
    assert billing_codes(OfficeVisit) == OfficeVisit.CPT


def test_visits_count_distinct_notes_in_the_window() -> None:
    """Two lines on one note are one visit; a visit outside the window does not count."""
    who = records.patient()
    code = first(OfficeVisit, "CPT")
    line = records.visit(who, code, "2027-01-10")
    records.visit(who, code, "2027-01-10", note=line.note)
    records.visit(who, code, "2025-01-10")
    assert ecqm(who).count_visits({code}, PERIOD) == 1


@pytest.mark.parametrize(
    "evidence",
    ["diagnosis", "encounter", "assessment", "intervention"],
)
def test_hospice_services_from_each_kind_of_evidence(evidence: str) -> None:
    """Hospice care counts from a diagnosis, an encounter, a 'yes' assessment, or an intervention."""
    who = records.patient()
    if evidence == "diagnosis":
        records.condition(who, records.SNOMEDCT, first(HospiceDiagnosis, "SNOMEDCT"))
    elif evidence == "encounter":
        records.visit(who, first(HospiceEncounter, "HCPCSLEVELII"), "2027-02-01")
    elif evidence == "assessment":
        records.observation(who, "45755-6", "373066001", "2027-02-01")
    else:
        records.instruction(who, records.SNOMEDCT, first(HospiceCareAmbulatory, "SNOMEDCT"), "2027-02-01")
    assert ecqm(who).has_hospice_services()
    assert ecqm(who).excluded()


def test_hospice_assessment_needs_a_yes() -> None:
    """A hospice assessment answered other than 'yes' does not exclude."""
    who = records.patient()
    records.observation(who, "45755-6", "373067005", "2027-02-01")
    assert not ecqm(who).has_hospice_services()


def test_palliative_care_diagnosis_excludes() -> None:
    """A palliative care diagnosis overlapping the period excludes."""
    who = records.patient()
    records.condition(who, records.ICD10, first(PalliativeCareDiagnosis, "ICD10CM"))
    assert ecqm(who).has_palliative_care()


def test_nursing_home_uses_the_most_recent_housing_status_and_age() -> None:
    """66+ living in a nursing home by their latest housing status is excluded; 65 is not."""
    moved_in, moved_out = records.patient(), records.patient()
    records.observation(moved_in, HOUSING_STATUS, LIVES_IN_NURSING_HOME, "2025-03-01")
    records.observation(moved_out, HOUSING_STATUS, LIVES_IN_NURSING_HOME, "2025-03-01")
    records.observation(moved_out, HOUSING_STATUS, "32911000", "2026-09-01")
    assert ecqm(moved_in, age=66).is_66_or_older_living_long_term_in_nursing_home()
    assert not ecqm(moved_in, age=65).is_66_or_older_living_long_term_in_nursing_home()
    assert not ecqm(moved_out, age=70).is_66_or_older_living_long_term_in_nursing_home()


def test_assessments_read_questionnaire_answers() -> None:
    """A housing status answered on a questionnaire counts like an observation."""
    who = records.patient()
    records.questionnaire_answer(who, "93025-5", HOUSING_STATUS, LIVES_IN_NURSING_HOME, "2026-01-01")
    assert ecqm(who, age=70).is_66_or_older_living_long_term_in_nursing_home()


def test_frailty_needs_advanced_illness_or_dementia_medication() -> None:
    """Frailty alone does not exclude; with an advanced illness or a dementia medication it does."""
    frail, frail_ill, frail_medicated = (records.patient() for _ in range(3))
    for who in (frail, frail_ill, frail_medicated):
        records.condition(who, records.ICD10, first(FrailtyDiagnosis, "ICD10CM"))
    records.condition(frail_ill, records.ICD10, first(AdvancedIllness, "ICD10CM"), onset="2025-09-01")
    records.medication(frail_medicated, first(DementiaMedications, "RXNORM"), "2025-09-01", "2025-12-01")
    assert not ecqm(frail).is_66_or_older_with_advanced_illness_and_frailty()
    assert ecqm(frail_ill).is_66_or_older_with_advanced_illness_and_frailty()
    assert ecqm(frail_medicated).is_66_or_older_with_advanced_illness_and_frailty()
    assert not ecqm(frail_ill, age=65).is_66_or_older_with_advanced_illness_and_frailty()


def test_no_evidence_means_no_exclusion() -> None:
    """A patient with no exclusion evidence is not excluded."""
    assert not ecqm(records.patient()).excluded()


@pytest.mark.parametrize(
    ("text", "number"),
    [("7.2", 7.2), (" >14 ", 14.0), ("<= 3", 3.0), ("see comment", None), ("", None)],
)
def test_parse_number(text: str, number: float | None) -> None:
    """Comparator results parse to their number; text results have none."""
    assert parse_number(text) == number


def test_every_copy_of_ecqm_common_is_identical() -> None:
    """Plugins cannot share code, so each carries a copy; they must not drift apart."""
    copies = sorted(PROTOCOLS.glob("*/protocols/ecqm_common.py"))
    assert len(copies) >= 2
    digests = {path.parent.parent.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}
    assert len(set(digests.values())) == 1, digests


def test_every_copy_of_the_test_records_is_identical() -> None:
    """The record builders are shared the same way."""
    copies = sorted(PROTOCOLS.glob("*/tests/records.py"))
    digests = {path.parent.parent.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in copies}
    assert len(set(digests.values())) == 1, digests
