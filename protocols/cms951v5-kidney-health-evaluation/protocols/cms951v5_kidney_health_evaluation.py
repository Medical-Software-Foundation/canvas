"""
CMS951v5 - Kidney Health Evaluation.

Patients 18-85 years of age at the start of the measurement period, with diabetes active
at its start and an outpatient visit during it, need a kidney health evaluation during the
period: an estimated glomerular filtration rate (eGFR) and a urine albumin-creatinine ratio
(uACR), where a urine albumin and a urine creatinine resulted within four days of each other
also count as the uACR. Patients with chronic kidney disease stage 5 or end-stage renal
disease, in hospice, or receiving palliative care are excluded.

A result counts when it has a numeric value (including comparator values such as ``<3``).
Canvas lab values carry no coded result, so "undetectable" results coded from the
Undetectable Lab Result Value value set do not count.

https://ecqi.healthit.gov/ecqm/ec/2027/cms0951v5
"""

from __future__ import annotations

import arrow
from django.db.models import Q

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.value_set.v2027.condition import (
    ChronicKidneyDiseaseStage5,
    Diabetes,
    EndStageRenalDisease,
)
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    OfficeVisit,
    OutpatientConsultation,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    TelephoneVisits,
)
from canvas_sdk.value_set.v2027.laboratory_test import (
    EstimatedGlomerularFiltrationRate,
    UrineAlbumin,
    UrineAlbuminCreatinineRatio,
    UrineCreatinine,
)

from .diabetes_quality_measure import DiabetesQualityMeasure
from .ecqm_common import age_in_years, billing_codes, coding_filter, parse_number

URINE_TEST_PAIRING_DAYS = 4


class ClinicalQualityMeasure951v5(DiabetesQualityMeasure):
    """CMS951v5 - Kidney health evaluation for patients with diabetes."""

    class Meta:
        title = "Kidney Health Evaluation"
        version = "2027-01-01v5"
        description = (
            "Patients 18-85 years of age with diabetes who have not had both an estimated "
            "glomerular filtration rate (eGFR) and a urine albumin-creatinine ratio (uACR) "
            "during the measurement period."
        )
        information = "https://ecqi.healthit.gov/ecqm/ec/2027/cms0951v5"
        identifiers = ["CMS951v5"]
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
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    AGE_RANGE_START = 18
    AGE_RANGE_END = 85
    QUALIFYING_VISIT_CODES = frozenset(
        set().union(
            *(
                billing_codes(value_set)
                for value_set in (
                    AnnualWellnessVisit,
                    HomeHealthcareServices,
                    OfficeVisit,
                    OutpatientConsultation,
                    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
                    PreventiveCareServicesInitialOfficeVisit18AndUp,
                    TelephoneVisits,
                )
            )
        )
    )

    # ----- population -----

    def age_at_start(self) -> int:
        """Completed years of age at the start of the measurement period."""
        return age_in_years(self.patient, self.timeframe.start)

    def has_diabetes_at_start(self) -> bool:
        """A diabetes diagnosis that began before the period and continues into it."""
        start = self.timeframe.start.date()
        return self.ecqm.conditions(coding_filter(Diabetes), self.timeframe).filter(
            Q(onset_date__isnull=True) | Q(onset_date__lt=start)
        ).exists()

    def in_initial_population(self) -> bool:
        """18-85 at the start of the period, diabetes active at its start, and an outpatient visit."""
        return (
            self.AGE_RANGE_START <= self.age_at_start() <= self.AGE_RANGE_END
            and self.has_diabetes_at_start()
            and self.has_qualifying_visit()
        )

    def is_excluded(self) -> bool:
        """CKD stage 5 or ESRD overlapping the period, hospice, or palliative care."""
        return (
            self.ecqm.has_condition(ChronicKidneyDiseaseStage5, self.timeframe)
            or self.ecqm.has_condition(EndStageRenalDisease, self.timeframe)
            or self.ecqm.has_hospice_services()
            or self.ecqm.has_palliative_care()
        )

    def first_due_in(self) -> int | None:
        """Days until the patient is 18 at the start of a period, if they have diabetes."""
        if self.age_at_start() < self.AGE_RANGE_START and self.has_diabetes_in_period():
            birthday = arrow.get(self.patient.birth_date)
            return (birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.start).days
        return None

    # ----- numerator -----

    def resulted_dates(self, value_set: type) -> list[arrow.Arrow]:
        """Dates of numeric results in the period for lab tests in ``value_set``."""
        return sorted(
            when
            for when, value in self.ecqm.lab_results(coding_filter(value_set), self.timeframe)
            if parse_number(value) is not None
        )

    def egfr_dates(self) -> list[arrow.Arrow]:
        """eGFR results in the period."""
        return self.resulted_dates(EstimatedGlomerularFiltrationRate)

    def uacr_dates(self) -> list[arrow.Arrow]:
        """uACR results, plus urine albumin results with a urine creatinine within four days."""
        dates = self.resulted_dates(UrineAlbuminCreatinineRatio)
        creatinine = self.resulted_dates(UrineCreatinine)
        for albumin in self.resulted_dates(UrineAlbumin):
            if any(
                abs((albumin - other).total_seconds()) <= URINE_TEST_PAIRING_DAYS * 86400
                for other in creatinine
            ):
                dates.append(albumin)
        return sorted(dates)

    def in_numerator(self) -> bool:
        """Both an eGFR and a uACR resulted during the period."""
        return bool(self.egfr_dates()) and bool(self.uacr_dates())

    # ----- cards -----

    def _satisfied_card(self) -> ProtocolCard:
        """Build a SATISFIED card; the evaluation is due a year after its earlier test."""
        evaluated = min(self.egfr_dates()[-1], self.uacr_dates()[-1])
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS951v5",
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            narrative=(
                f"{self.patient.first_name} has diabetes and had an eGFR and a urine "
                f"albumin-creatinine ratio, most recently {self.display_date(evaluated)}."
            ),
            due_in=(evaluated.shift(days=self.timeframe.duration) - self.now).days,
        )

    def _due_card(self) -> ProtocolCard:
        """Build a DUE card naming the missing tests."""
        missing = [
            name
            for name, dates in (
                ("an eGFR", self.egfr_dates()),
                ("a urine albumin-creatinine ratio", self.uacr_dates()),
            )
            if not dates
        ]
        card = ProtocolCard(
            patient_id=self.patient.id,
            key="CMS951v5",
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            narrative=(
                f"{self.patient.first_name} has diabetes and no record of "
                f"{' or '.join(missing)} in the last year."
            ),
            due_in=-1,
        )
        card.add_recommendation(
            title="Order eGFR and urine albumin-creatinine ratio", button="Order"
        )
        return card

    def compute(self) -> list[Effect]:
        """Emit a single ProtocolCard for the patient's kidney health evaluation."""
        if not self.in_denominator():
            card = ProtocolCard(
                patient_id=self.patient.id,
                key="CMS951v5",
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
            return [card.apply()]

        if self.in_numerator():
            return [self._satisfied_card().apply()]
        return [self._due_card().apply()]
