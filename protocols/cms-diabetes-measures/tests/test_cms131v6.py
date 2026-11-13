"""CMS131v15 diabetic eye exam, against real records."""

from __future__ import annotations

from canvas_sdk.value_set.v2027.communication import (
    AutonomousEyeExamResultOrFinding,
    DiabeticRetinopathySeverityLevel,
)
from canvas_sdk.value_set.v2027.condition import Diabetes, DiabeticRetinopathy
from canvas_sdk.value_set.v2027.encounter import OfficeVisit
from canvas_sdk.value_set.v2027.physical_exam import RetinalOrDilatedEyeExam

from protocols.cms131v6_diabetes_eye_exam import (
    AUTONOMOUS_EYE_EXAM,
    BILATERAL_ANOPHTHALMOS,
    LEFT_EYE_SEVERITY,
    NO_APPARENT_RETINOPATHY,
    RIGHT_EYE_SEVERITY,
    ClinicalQualityMeasure131v6,
)

from . import records

RETINAL_EXAM = sorted(RetinalOrDilatedEyeExam.SNOMEDCT)[0]


def eligible():  # noqa: ANN201
    """A patient with diabetes and an office visit in the measurement period."""
    who = records.patient()
    records.condition(who, records.ICD10, sorted(Diabetes.ICD10CM)[0])
    records.visit(who, sorted(OfficeVisit.CPT)[0], "2027-01-10")
    return who


def status(who) -> str:  # noqa: ANN001
    return records.card(records.build(ClinicalQualityMeasure131v6, who).compute())["status"]


def first(value_set, system: str) -> str:  # noqa: ANN001
    return sorted(getattr(value_set, system))[0]


def test_no_exam_is_due() -> None:
    """Without any qualifying exam or finding the patient is due."""
    assert status(eligible()) == "due"


def test_exam_in_the_period_satisfies() -> None:
    """A retinal exam referral report in the period satisfies."""
    who = eligible()
    records.referral_report(who, records.SNOMEDCT, RETINAL_EXAM, "2027-02-01")
    assert status(who) == "satisfied"


def test_prior_year_exam_satisfies_only_without_retinopathy() -> None:
    """An exam in the year before counts when the patient has no diabetic retinopathy."""
    without, with_retinopathy = eligible(), eligible()
    for who in (without, with_retinopathy):
        records.referral_report(who, records.SNOMEDCT, RETINAL_EXAM, "2026-03-01")
    records.condition(with_retinopathy, records.ICD10, first(DiabeticRetinopathy, "ICD10CM"))
    assert status(without) == "satisfied"
    assert status(with_retinopathy) == "due"


def test_autonomous_eye_exam_satisfies() -> None:
    """An AI eye exam in the period with a result in the value set satisfies."""
    who = eligible()
    records.observation(
        who, AUTONOMOUS_EYE_EXAM, first(AutonomousEyeExamResultOrFinding, "LOINC"), "2027-02-01"
    )
    assert status(who) == "satisfied"


def test_severity_in_one_eye_needs_a_clear_prior_finding_for_the_other() -> None:
    """A left-eye severity finding satisfies with a prior 'no apparent retinopathy' right eye."""
    alone, paired = eligible(), eligible()
    severity = sorted(DiabeticRetinopathySeverityLevel.LOINC - {NO_APPARENT_RETINOPATHY})[0]
    for who in (alone, paired):
        records.observation(who, LEFT_EYE_SEVERITY, severity, "2027-02-01")
    records.observation(paired, RIGHT_EYE_SEVERITY, NO_APPARENT_RETINOPATHY, "2026-02-01")
    assert status(alone) == "due"
    assert status(paired) == "satisfied"


def test_clear_findings_for_both_eyes_in_the_prior_year_satisfy() -> None:
    """'No apparent retinopathy' for both eyes in the year before the period satisfies."""
    who = eligible()
    records.observation(who, LEFT_EYE_SEVERITY, NO_APPARENT_RETINOPATHY, "2026-02-01")
    records.observation(who, RIGHT_EYE_SEVERITY, NO_APPARENT_RETINOPATHY, "2026-02-01")
    assert status(who) == "satisfied"


def test_bilateral_absence_of_eyes_excludes() -> None:
    """Anophthalmos of both eyes takes the patient out of the denominator."""
    who = eligible()
    records.condition(who, records.SNOMEDCT, BILATERAL_ANOPHTHALMOS)
    assert status(who) == "not_applicable"
