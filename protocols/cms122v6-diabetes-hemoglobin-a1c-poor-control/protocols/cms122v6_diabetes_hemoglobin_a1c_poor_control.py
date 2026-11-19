"""
CMS122v15 - Diabetes: Glycemic Status Assessment Greater Than 9%.

Patients 18-75 with diabetes are in the numerator (the *poor control* sense; this is an
inverse measure) when their most recent glycemic status assessment (HbA1c or glucose
management indicator) in the measurement period is above 9.0%, has no result, or is
missing. A numeric result is preferred over a more recent result without a value; when
several numeric results share the most recent day, the lowest counts. A SATISFIED card
means the patient is *not* in poor control.

https://ecqi.healthit.gov/ecqm/ec/2027/cms0122v15
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    NutritionServices,
    OfficeVisit,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    TelephoneVisits,
)
from canvas_sdk.value_set.v2027.laboratory_test import Hba1cLaboratoryTest

from .diabetes_quality_measure import DiabetesQualityMeasure
from .ecqm_common import LOINC, billing_codes, code_filter, coding_filter, parse_number

GLUCOSE_MANAGEMENT_INDICATOR = "97506-0"
# Medical nutrition therapy visits the measure names by code.
MEDICAL_NUTRITION_THERAPY = frozenset({"97802", "97803", "97804", "G0270", "G0271"})


class ClinicalQualityMeasure122v6(DiabetesQualityMeasure):
    """CMS122v15 - Glycemic status assessment greater than 9%."""

    class Meta:
        title = "Diabetes: Glycemic Status Assessment Greater Than 9%"
        version = "2027-01-01v15"
        description = (
            "Patients 18-75 years of age with diabetes whose most recent glycemic status "
            "assessment (HbA1c or glucose management indicator) is above 9.0% or missing "
            "during the measurement period."
        )
        information = "https://ecqi.healthit.gov/ecqm/ec/2027/cms0122v15"
        identifiers = ["CMS122v15"]
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
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_UPDATED),
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
                    NutritionServices,
                    TelephoneVisits,
                )
            )
        )
        | MEDICAL_NUTRITION_THERAPY
    )

    MAXIMUM_CONTROLLED = 9.0

    _assessments: list[tuple[arrow.Arrow, float | None]] | None = None

    @property
    def assessments(self) -> list[tuple[arrow.Arrow, float | None]]:
        """``(date, value)`` for each HbA1c or GMI result in the period, oldest first."""
        if self._assessments is None:
            match = coding_filter(Hba1cLaboratoryTest) | code_filter(
                LOINC, GLUCOSE_MANAGEMENT_INDICATOR
            )
            self._assessments = sorted(
                (
                    (when, parse_number(value))
                    for when, value in self.ecqm.lab_results(match, self.timeframe)
                ),
                key=lambda result: result[0],
            )
        return self._assessments

    @property
    def most_recent(self) -> tuple[arrow.Arrow, float | None] | None:
        """The assessment that decides the measure, per the v15 "Most Recent" rules.

        The lowest result on the most recent day with a result above 0%; otherwise the most
        recent numeric result; otherwise the most recent result without a value; ``None``
        when there is no assessment.
        """
        numeric = [result for result in self.assessments if result[1] is not None]
        positive = [result for result in numeric if (result[1] or 0.0) > 0]
        if positive:
            latest_day = max(when.date() for when, _ in positive)
            same_day = [result for result in numeric if result[0].date() == latest_day]
            return min(same_day, key=lambda result: result[1] or 0.0)
        if numeric:
            return numeric[-1]
        return self.assessments[-1] if self.assessments else None

    def in_numerator(self) -> bool:
        """No assessment, a most recent assessment without a result, or one above 9.0%."""
        most_recent = self.most_recent
        if most_recent is None or most_recent[1] is None:
            return True
        return most_recent[1] > self.MAXIMUM_CONTROLLED

    def _due_card(self) -> ProtocolCard:
        """Build a DUE card recommending either an assessment order or a care instruction."""
        first_name = self.patient.first_name
        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS122v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        most_recent = self.most_recent
        if most_recent is None:
            card.narrative = (
                f"{first_name} has no HbA1c or glucose management indicator result in the last year."
            )
            card.add_recommendation(title="Order HbA1c", button="Order")
        elif most_recent[1] is None:
            card.narrative = (
                f"{first_name}'s last glycemic status assessment done "
                f"{self.display_date(most_recent[0])} has no numeric result."
            )
            card.add_recommendation(title="Order HbA1c", button="Order")
        else:
            card.narrative = (
                f"{first_name}'s last glycemic status assessment done "
                f"{self.display_date(most_recent[0])} was {most_recent[1]:.1f}%."
            )
            card.add_recommendation(
                title=(
                    "Discuss lifestyle modification and medication adherence. "
                    "Consider diabetes education and medication intensification as appropriate."
                ),
                button="Instruct",
            )
        return card

    def _satisfied_card(self) -> ProtocolCard:
        """Build a SATISFIED card describing the deciding assessment."""
        when, value = self.most_recent or (self.now, None)
        due_in = (when.shift(days=self.timeframe.duration) - self.now).days
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS122v6",
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            narrative=(
                f"{self.patient.first_name}'s last glycemic status assessment done "
                f"{self.display_date(when)} was {value:.1f}%."
            ),
            due_in=due_in,
        )

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard effect summarizing this patient's glycemic status."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS122v6",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        if self.in_numerator():
            return [self._due_card().apply()]
        return [self._satisfied_card().apply()]
