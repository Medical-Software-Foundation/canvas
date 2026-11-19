"""CMS130v15 Colorectal Cancer Screening clinical quality measure.

Surfaces a Protocol Card recommending colorectal cancer screening for adults 46-75 years of
age at the end of the measurement period, with a qualifying visit during it, who have not
had appropriate screening, and marks the card satisfied for patients with any of:

- a fecal occult blood test (FOBT) with a result during the measurement period;
- a stool DNA with FIT test with a result during the period or the two years before it;
- a flexible sigmoidoscopy or CT colonography during the period or the four years before it;
- a colonoscopy during the period or the nine years before it.

Excluded from the denominator: a diagnosis or history of colorectal cancer or a total
colectomy on or before the end of the period, plus hospice, palliative care, and the age
66+ nursing home and frailty exclusions (``ecqm_common``).

Lab tests come from lab values. Procedures and diagnostic studies come from referral and
imaging reports, procedures, and billing line items.

https://ecqi.healthit.gov/ecqm/ec/2027/cms0130v15
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.imaging import ImagingReport
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.referral import ReferralReport
from canvas_sdk.value_set.v2027.condition import MalignantNeoplasmOfColon
from canvas_sdk.value_set.v2027.diagnostic_study import CtColonography
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    OfficeVisit,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    TelephoneVisits,
    VirtualEncounter,
)
from canvas_sdk.value_set.v2027.laboratory_test import FecalOccultBloodTestFobt, SdnaFitTest
from canvas_sdk.value_set.v2027.procedure import (
    Colonoscopy,
    FlexibleSigmoidoscopy,
    TotalColectomy,
)
from canvas_sdk.value_set.value_set import ValueSet

from .ecqm_common import EcqmPatient, age_in_years, billing_codes, coding_filter

# AdultOutpatientEncountersQDM "Qualifying Encounters".
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
                VirtualEncounter,
                TelephoneVisits,
            )
        )
    )
)

# Years before the measurement period each screening still counts.
SCREENING_LOOKBACK_YEARS = {
    "FOBT": 0,
    "sDNA FIT test": 2,
    "flexible sigmoidoscopy": 4,
    "CT colonography": 4,
    "colonoscopy": 9,
}


class ClinicalQualityMeasure130v6(ClinicalQualityMeasure):
    """Colorectal Cancer Screening (CMS130v15)."""

    class Meta:
        title = "Colorectal Cancer Screening"
        version = "2027-01-01v15"
        description = (
            "Adults 46-75 years of age who have not had appropriate screening for "
            "colorectal cancer."
        )
        information = "https://ecqi.healthit.gov/ecqm/ec/2027/cms0130v15"
        identifiers = ["CMS130v15"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]
        references = [
            "U.S. Preventive Services Task Force. (2021). Screening for colorectal cancer: US "
            "Preventive Services Task Force recommendation statement. JAMA, 325(19), 1965-1977."
        ]

    RESPONDS_TO = [
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_UPDATED),
        EventType.Name(EventType.CONDITION_ASSESSED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.CONDITION_RESOLVED),
        EventType.Name(EventType.CONDITION_UPDATED),
        EventType.Name(EventType.IMAGING_REPORT_CREATED),
        EventType.Name(EventType.IMAGING_REPORT_UPDATED),
        EventType.Name(EventType.INSTRUCTION_CREATED),
        EventType.Name(EventType.INSTRUCTION_UPDATED),
        EventType.Name(EventType.INTERVIEW_CREATED),
        EventType.Name(EventType.INTERVIEW_UPDATED),
        EventType.Name(EventType.LAB_REPORT_CREATED),
        EventType.Name(EventType.LAB_REPORT_UPDATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.REFERRAL_REPORT_CREATED),
        EventType.Name(EventType.REFERRAL_REPORT_UPDATED),
    ]

    PROTOCOL_KEY = "CMS130v6"
    AGE_RANGE_START = 46
    AGE_RANGE_END = 75

    _patient: Patient | None = None
    _ecqm: EcqmPatient | None = None

    @property
    def patient(self) -> Patient:
        """Return the Patient this protocol is being computed for, fetched once per instance."""
        if self._patient is None:
            self._patient = Patient.objects.get(id=self.patient_id_from_target())
        return self._patient

    @property
    def ecqm(self) -> EcqmPatient:
        """eCQM data access for this patient and measurement period, built once per instance."""
        if self._ecqm is None:
            self._ecqm = EcqmPatient(self.patient.id, self.timeframe, self.age())
        return self._ecqm

    # ----- population -----

    def age(self) -> int:
        """Completed years of age at the end of the measurement period."""
        return age_in_years(self.patient, self.timeframe.end)

    def in_initial_population(self) -> bool:
        """Adults 46-75 at the end of the period with a qualifying visit during it."""
        return (
            self.AGE_RANGE_START <= self.age() <= self.AGE_RANGE_END
            and self.ecqm.count_visits(set(QUALIFYING_VISIT_CODES), self.timeframe) > 0
        )

    def had_colon_exclusion(self) -> bool:
        """A diagnosis or history of colorectal cancer, or a total colectomy, by the period end."""
        end = self.timeframe.end
        return self.ecqm.has_condition_starting_by(
            coding_filter(MalignantNeoplasmOfColon), end
        ) or self.ecqm.has_procedure_by(TotalColectomy, end)

    def in_denominator(self) -> bool:
        """The initial population minus the exclusions."""
        return (
            self.in_initial_population()
            and not self.had_colon_exclusion()
            and not self.ecqm.excluded()
        )

    def first_due_in(self) -> int | None:
        """Return days until the patient first becomes eligible, or None if not applicable."""
        if self.age() >= self.AGE_RANGE_START:
            return None
        birthday = arrow.get(self.patient.birth_date)
        return (birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.end).days

    # ----- numerator -----

    def lab_dates(self, value_set: type[ValueSet], window: Timeframe) -> list[arrow.Arrow]:
        """Dates of lab results with any value for tests in ``value_set``."""
        return [
            when for when, value in self.ecqm.lab_results(coding_filter(value_set), window) if value
        ]

    def exam_dates(self, value_set: type[ValueSet], window: Timeframe) -> list[arrow.Arrow]:
        """Dates of procedures or studies in ``value_set``: reports, procedures, and billing."""
        billed = [
            arrow.get(when)
            for when in self.ecqm.encounters(billing_codes(value_set), window).values_list(
                "note__datetime_of_service", flat=True
            )
        ]
        return (
            self.ecqm.report_dates(ReferralReport.objects.all(), value_set, window)
            + self.ecqm.report_dates(ImagingReport.objects.all(), value_set, window)
            + self.ecqm.procedure_dates(value_set, window)
            + billed
        )

    def screenings(self) -> list[tuple[str, arrow.Arrow]]:
        """``(screening name, date)`` for every qualifying screening, longest-lasting first.

        A colonoscopy five years ago keeps the patient covered longer than an FOBT last
        month, so the card reports whichever screening expires last.
        """
        found: list[tuple[str, arrow.Arrow]] = []
        for name, value_set, dates in (
            ("FOBT", FecalOccultBloodTestFobt, self.lab_dates),
            ("sDNA FIT test", SdnaFitTest, self.lab_dates),
            ("flexible sigmoidoscopy", FlexibleSigmoidoscopy, self.exam_dates),
            ("CT colonography", CtColonography, self.exam_dates),
            ("colonoscopy", Colonoscopy, self.exam_dates),
        ):
            window = self.ecqm.before_and_during(years=SCREENING_LOOKBACK_YEARS[name])
            found.extend((name, when) for when in dates(value_set, window))
        return sorted(
            found,
            key=lambda screening: screening[1].shift(years=SCREENING_LOOKBACK_YEARS[screening[0]]),
            reverse=True,
        )

    def in_numerator(self) -> bool:
        """True if the patient has any qualifying screening within its look-back window."""
        return bool(self.screenings())

    # ----- cards -----

    def _recommendation_context(self) -> dict:
        """Return the shared context (encounter diagnosis) for every recommendation."""
        return {
            "conditions": [
                [
                    {
                        "code": "Z1211",
                        "system": "ICD-10",
                        "display": "Encounter for screening for malignant neoplasm of colon",
                    }
                ]
            ]
        }

    def _satisfied_card(self, name: str, when: arrow.Arrow) -> ProtocolCard:
        """Build the protocol card for a patient who is up to date."""
        expires = when.shift(years=SCREENING_LOOKBACK_YEARS[name], days=self.timeframe.duration)
        return ProtocolCard(
            patient_id=self.patient.id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=f"{self.patient.first_name} had a {name} on {when.format('M/D/YY')}.",
            status=ProtocolCard.Status.SATISFIED,
            due_in=(expires - self.now).days,
        )

    def _due_card(self) -> ProtocolCard:
        """Build the protocol card for a patient due for screening, with recommendations."""
        card = ProtocolCard(
            patient_id=self.patient.id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=f"{self.patient.first_name} is due for a Colorectal Cancer Screening.",
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        context = self._recommendation_context()
        card.add_recommendation(
            title="Order a FOBT",
            button="Order",
            command="labOrder",
            context={**context, "lab": sorted(FecalOccultBloodTestFobt.values.get("LOINC", set()))},
        )
        card.add_recommendation(
            title="Order a sDNA FIT test",
            button="Order",
            command="labOrder",
            context={**context, "lab": sorted(SdnaFitTest.values.get("LOINC", set()))},
        )
        card.add_recommendation(
            title="Order a Flexible sigmoidoscopy",
            button="Order",
            command="refer",
            context={**context, "specialties": ["Gastroenterology"]},
        )
        card.add_recommendation(
            title="Order a CT Colonography",
            button="Order",
            command="imagingOrder",
            context={**context, "specialties": ["Radiology"]},
        )
        card.add_recommendation(
            title="Order a Colonoscopy",
            button="Order",
            command="refer",
            context={**context, "specialties": ["Gastroenterology"]},
        )
        return card

    def _not_applicable_card(self) -> ProtocolCard:
        """Build a protocol card for a patient outside the population or excluded."""
        due_in = self.first_due_in()
        return ProtocolCard(
            patient_id=self.patient.id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            narrative=(
                f"{self.patient.first_name} is not currently in the CMS130 measure population."
            ),
            status=ProtocolCard.Status.NOT_APPLICABLE,
            due_in=due_in if due_in is not None else -1,
        )

    def compute(self) -> list[Effect]:
        """Compute the protocol's effect list for the current event."""
        if not self.in_denominator():
            return [self._not_applicable_card().apply()]
        screenings = self.screenings()
        if screenings:
            return [self._satisfied_card(*screenings[0]).apply()]
        return [self._due_card().apply()]
