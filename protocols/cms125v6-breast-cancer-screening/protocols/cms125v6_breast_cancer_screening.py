"""CMS125v15 Breast Cancer Screening protocol.

Identifies women 42-74 years of age at the end of the measurement period, with a qualifying
visit during it, who have not had a mammogram from October 1 two years before the period
through its end (the period plus a 15-month lookback, 27 months in all), and recommends one.

Excluded from the denominator:

- hospice, palliative care, age 66+ living long term in a nursing home, or age 66+ with
  frailty and an advanced illness or dementia medication (``ecqm_common``);
- a bilateral mastectomy (procedure or history diagnosis), or evidence of both a right and
  a left mastectomy, each side shown by a status-post diagnosis or a unilateral mastectomy
  procedure for that side.

A unilateral mastectomy coded without a side counts in the spec only with a recorded body
site; Canvas procedures carry no body site, so those procedures do not count toward a side.

https://ecqi.healthit.gov/ecqm/ec/2027/cms0125v15
"""

from __future__ import annotations

import arrow

from canvas_sdk.commands import InstructCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.v1.data.imaging import ImagingReport
from canvas_sdk.v1.data.patient import Patient, SexAtBirth
from canvas_sdk.value_set.v2027.condition import (
    HistoryOfBilateralMastectomy,
    StatusPostLeftMastectomy,
    StatusPostRightMastectomy,
)
from canvas_sdk.value_set.v2027.diagnostic_study import Mammography
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    OfficeVisit,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    TelephoneVisits,
    VirtualEncounter,
)
from canvas_sdk.value_set.v2027.procedure import (
    BilateralMastectomy,
    UnilateralMastectomyLeft,
    UnilateralMastectomyRight,
)

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


class ClinicalQualityMeasure125v6(ClinicalQualityMeasure):
    """Breast Cancer Screening (CMS125v15)."""

    class Meta:
        title = "Breast Cancer Screening"
        version = "2027-01-01v15"

        # 27 months, displayed as 2 years, 3 months.
        default_display_interval_in_days = (365 * 2) + (3 * 30)

        description = (
            "Women 42-74 years of age who have not had a mammogram to screen for breast "
            "cancer within the last 27 months."
        )
        information = "https://ecqi.healthit.gov/ecqm/ec/2027/cms0125v15"
        identifiers = ["CMS125v15"]
        types = ["CQM"]
        authors = ["National Committee for Quality Assurance"]
        references = [
            "U.S. Preventive Services Task Force. (2024). Screening for breast cancer: US "
            "Preventive Services Task Force recommendation statement. JAMA, 331(22), 1918-1930."
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
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_UPDATED),
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    AGE_RANGE_START = 42
    AGE_RANGE_END = 74
    EXTRA_SCREENING_MONTHS = 15
    PROTOCOL_KEY = "CMS125v6_RECOMMEND_MAMMOGRAPHY"
    RECOMMENDATION_TITLE = "Discuss breast cancer screening and order imaging as appropriate"

    _patient: Patient | None = None
    _ecqm: EcqmPatient | None = None
    _on_date: arrow.Arrow | None = None

    @property
    def patient(self) -> Patient:
        """The patient this protocol is computing for, fetched once per instance."""
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

    @property
    def is_female(self) -> bool:
        """Whether the patient is recorded as female at birth."""
        return self.patient.sex_at_birth == SexAtBirth.FEMALE

    def in_initial_population(self) -> bool:
        """Women 42-74 at the end of the period with a qualifying visit during it."""
        return (
            self.is_female
            and self.AGE_RANGE_START <= self.age() <= self.AGE_RANGE_END
            and self.ecqm.count_visits(set(QUALIFYING_VISIT_CODES), self.timeframe) > 0
        )

    def had_mastectomy(self) -> bool:
        """A bilateral mastectomy, or mastectomy evidence for both the right and the left side."""
        end = self.timeframe.end
        if self.ecqm.has_condition_starting_by(coding_filter(HistoryOfBilateralMastectomy), end):
            return True
        if self.ecqm.has_procedure_by(BilateralMastectomy, end):
            return True
        right = self.ecqm.has_condition_starting_by(
            coding_filter(StatusPostRightMastectomy), end
        ) or self.ecqm.has_procedure_by(UnilateralMastectomyRight, end)
        left = self.ecqm.has_condition_starting_by(
            coding_filter(StatusPostLeftMastectomy), end
        ) or self.ecqm.has_procedure_by(UnilateralMastectomyLeft, end)
        return right and left

    def in_denominator(self) -> bool:
        """The initial population minus the exclusions."""
        return (
            self.in_initial_population()
            and not self.ecqm.excluded()
            and not self.had_mastectomy()
        )

    def in_numerator(self) -> bool:
        """A mammogram in the period or the 15 months before it."""
        window = self.ecqm.before_and_during(months=self.EXTRA_SCREENING_MONTHS)
        dates = self.ecqm.report_dates(ImagingReport.objects.all(), Mammography, window)
        if not dates:
            return False
        self._on_date = max(dates)
        return True

    def first_due_in(self) -> int | None:
        """Days until a woman becomes age-eligible; ``None`` if already eligible or not female."""
        if self.is_female and self.age() < self.AGE_RANGE_START:
            birthday = arrow.get(self.patient.birth_date)
            return (birthday.shift(years=self.AGE_RANGE_START) - self.timeframe.end).days
        return None

    # ----- cards -----

    def screening_interval_context(self) -> str:
        """Human-readable description of the 27-month screening interval (12 + 15 lookback)."""
        years, months = divmod(12 + self.EXTRA_SCREENING_MONTHS, 12)
        return f"Current screening interval {years} years, {months} months."

    def _build_due_card(self, patient_id: str) -> ProtocolCard:
        """Build the protocol card returned when the patient is due for a mammogram."""
        card = ProtocolCard(
            patient_id=patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            status=ProtocolCard.Status.DUE,
            due_in=-1,
        )
        card.narrative = "No relevant exams found.\n" + self.screening_interval_context()
        card.add_recommendation(
            title=self.RECOMMENDATION_TITLE,
            button="Counsel",
            commands=[InstructCommand()],
        )
        return card

    def _build_satisfied_card(self, patient_id: str, on_date: arrow.Arrow) -> ProtocolCard:
        """Build the protocol card returned when a recent mammogram satisfies the measure."""
        due_in = (
            on_date.shift(days=self.timeframe.duration, months=self.EXTRA_SCREENING_MONTHS)
            - self.now
        ).days
        card = ProtocolCard(
            patient_id=patient_id,
            key=self.PROTOCOL_KEY,
            title=self.Meta.title,
            status=ProtocolCard.Status.SATISFIED,
            due_in=due_in,
        )
        card.narrative = (
            f"{self.patient.first_name} had a mammography "
            f"{on_date.humanize(self.now)} on {on_date.format('M/D/YY')}."
        )
        return card

    def compute(self) -> list[Effect]:
        """Compute the protocol effect(s) in response to an event."""
        patient_id = self.patient.id
        if self.in_denominator():
            if self.in_numerator() and self._on_date:
                card = self._build_satisfied_card(patient_id, self._on_date)
            else:
                card = self._build_due_card(patient_id)
        else:
            card = ProtocolCard(
                patient_id=patient_id,
                key=self.PROTOCOL_KEY,
                title=self.Meta.title,
                status=ProtocolCard.Status.NOT_APPLICABLE,
                due_in=self.first_due_in() or -1,
            )
        return [card.apply()]
