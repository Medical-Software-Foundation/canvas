"""
CMS131v15 - Diabetes: Eye Exam.

Patients 18-75 with diabetes are numerator-compliant with any of:

- diabetic retinopathy overlapping the measurement period and a retinal or dilated eye
  exam during it;
- no diabetic retinopathy and a retinal or dilated eye exam during the period or the year
  before it;
- an autonomous (artificial intelligence) eye exam during the period with a result;
- a retinopathy severity level finding during the period for both eyes, or for one eye
  with a "no apparent retinopathy" finding for the other in the year before;
- "no apparent retinopathy" findings for both eyes in the year before the period.

Retinal exams by an eye care professional come from referral reports and procedures.
Autonomous exams and severity findings are coded assessments: a questionnaire answer or an
observation carrying the LOINC code and a result code.

https://ecqi.healthit.gov/ecqm/ec/2027/cms0131v15
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.referral import ReferralReport
from canvas_sdk.value_set.v2027.communication import (
    AutonomousEyeExamResultOrFinding,
    DiabeticRetinopathySeverityLevel,
)
from canvas_sdk.value_set.v2027.condition import DiabeticRetinopathy
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    OfficeVisit,
    OphthalmologicalServices,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    TelephoneVisits,
)
from canvas_sdk.value_set.v2027.physical_exam import RetinalOrDilatedEyeExam

from .diabetes_quality_measure import DiabetesQualityMeasure
from .ecqm_common import SNOMEDCT, billing_codes, code_filter, codes_in

AUTONOMOUS_EYE_EXAM = "105914-6"  # Eye Diabetic retinopathy screening Autonomous AI
LEFT_EYE_SEVERITY = "71490-7"  # Left eye Diabetic retinopathy severity level by Ophthalmoscopy
RIGHT_EYE_SEVERITY = "71491-5"  # Right eye Diabetic retinopathy severity level by Ophthalmoscopy
NO_APPARENT_RETINOPATHY = "LA18643-9"
BILATERAL_ANOPHTHALMOS = "15665641000119103"  # Anophthalmos of bilateral eyes (disorder)


class ClinicalQualityMeasure131v6(DiabetesQualityMeasure):
    """CMS131v15 - Diabetic eye exam."""

    class Meta:
        title = "Diabetes: Eye Exam"
        version = "2027-01-01v15"
        description = (
            "Patients 18-75 years of age with diabetes who have not had a retinal or "
            "dilated eye exam by an eye care professional, an autonomous eye exam, or a "
            "retinopathy severity finding in the measurement period, or a negative exam in "
            "the year before it when they have no diabetic retinopathy."
        )
        information = "https://ecqi.healthit.gov/ecqm/ec/2027/cms0131v15"
        identifiers = ["CMS131v15"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]

    RESPONDS_TO = [
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_UPDATED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.INSTRUCTION_CREATED),
        EventType.Name(EventType.INSTRUCTION_UPDATED),
        EventType.Name(EventType.INTERVIEW_CREATED),
        EventType.Name(EventType.INTERVIEW_UPDATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.REFERRAL_REPORT_CREATED),
        EventType.Name(EventType.REFERRAL_REPORT_UPDATED),
    ]

    QUALIFYING_VISIT_CODES = frozenset(
        set().union(
            *(
                billing_codes(value_set)
                for value_set in (
                    OfficeVisit,
                    AnnualWellnessVisit,
                    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
                    PreventiveCareServicesInitialOfficeVisit18AndUp,
                    HomeHealthcareServices,
                    OphthalmologicalServices,
                    TelephoneVisits,
                )
            )
        )
    )

    _satisfied_by: str = ""
    _on_date: arrow.Arrow | None = None

    # ----- windows -----

    def year_before(self) -> Timeframe:
        """The year before the measurement period."""
        return Timeframe(
            start=self.timeframe.start.shift(years=-1), end=self.timeframe.end.shift(years=-1)
        )

    # ----- exclusions -----

    def has_bilateral_absence_of_eyes(self) -> bool:
        """Anophthalmos of both eyes starting on or before the end of the period."""
        return self.ecqm.has_condition_starting_by(
            code_filter(SNOMEDCT, BILATERAL_ANOPHTHALMOS), self.timeframe.end
        )

    def is_excluded(self) -> bool:
        """The cross-cutting exclusions plus bilateral absence of eyes."""
        return super().is_excluded() or self.has_bilateral_absence_of_eyes()

    # ----- numerator -----

    def retinal_exam_dates(self, window: Timeframe) -> list[arrow.Arrow]:
        """Retinal or dilated eye exams in ``window``: referral reports and procedures."""
        return sorted(
            self.ecqm.report_dates(ReferralReport.objects.all(), RetinalOrDilatedEyeExam, window)
            + self.ecqm.procedure_dates(RetinalOrDilatedEyeExam, window)
        )

    def finding_dates(self, code: str, results: set[str], window: Timeframe) -> list[arrow.Arrow]:
        """Dates of the coded eye finding within ``window`` whose result is in ``results``."""
        return sorted(
            when for when, result in self.ecqm.assessment_results(code, window) if result in results
        )

    def _satisfy(self, reason: str, dates: list[arrow.Arrow]) -> bool:
        self._satisfied_by = reason
        self._on_date = dates[-1] if dates else None
        return True

    def in_numerator(self) -> bool:
        """Any of the five v15 numerator paths (see the module docstring)."""
        period = self.timeframe
        prior = self.year_before()
        exams_in_period = self.retinal_exam_dates(period)
        if self.ecqm.has_condition(DiabeticRetinopathy, period):
            if exams_in_period:
                return self._satisfy("a retinal examination", exams_in_period)
        else:
            exams = self.retinal_exam_dates(self.ecqm.before_and_during(years=1))
            if exams:
                return self._satisfy("a retinal examination", exams)

        autonomous = self.finding_dates(
            AUTONOMOUS_EYE_EXAM, codes_in(AutonomousEyeExamResultOrFinding), period
        )
        if autonomous:
            return self._satisfy("an autonomous eye exam", autonomous)

        severity = codes_in(DiabeticRetinopathySeverityLevel)
        none_found = {NO_APPARENT_RETINOPATHY}
        left = self.finding_dates(LEFT_EYE_SEVERITY, severity, period)
        right = self.finding_dates(RIGHT_EYE_SEVERITY, severity, period)
        left_clear = self.finding_dates(LEFT_EYE_SEVERITY, none_found, prior)
        right_clear = self.finding_dates(RIGHT_EYE_SEVERITY, none_found, prior)
        if (left and right) or (left and right_clear) or (right and left_clear):
            return self._satisfy("a retinopathy severity finding", sorted(left + right))
        if left_clear and right_clear:
            return self._satisfy(
                "findings of no apparent retinopathy in both eyes", sorted(left_clear + right_clear)
            )
        return False

    # ----- cards -----

    def _satisfied_card(self) -> ProtocolCard:
        """Build a SATISFIED card naming what met the measure."""
        on_date = self._on_date or self.now
        due_in = (on_date.shift(days=self.timeframe.duration) - self.now).days
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS131v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            narrative=(
                f"{self.patient.first_name} has diabetes and {self._satisfied_by} was done "
                f"{self.display_date(on_date)}."
            ),
            due_in=due_in,
        )

    def _due_card(self) -> ProtocolCard:
        """Build a DUE card with perform/refer recommendations."""
        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS131v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            narrative=(
                f"{self.patient.first_name} has diabetes and no documentation of a retinal "
                "examination that meets the measure."
            ),
            due_in=-1,
        )
        card.add_recommendation(title="Perform retinal examination", button="Perform")
        card.add_recommendation(title="Refer for retinal examination", button="Refer")
        return card

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard for the patient's eye-exam status."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS131v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        if self.in_numerator():
            return [self._satisfied_card().apply()]
        return [self._due_card().apply()]
