"""CMS138v15 - Preventive Care and Screening: Tobacco Use: Screening and Cessation Intervention.

Three-population clinical quality measure that screens patients 12 and older for tobacco
use during the measurement period and recommends cessation counseling or pharmacotherapy
for current tobacco users.

Populations:
    - Population 1: patients screened for tobacco use during the measurement period.
    - Population 2: patients whose most recent screening identified a tobacco user, who
      received a cessation intervention during the period or the six months before it.
    - Population 3: composite of Populations 1 and 2.

Initial population: patients 12 or older at the start of the measurement period with at
least two qualifying visits or one preventive visit during it. Patients in hospice are
excluded.

Only the most recent screening in the period decides tobacco use status. Screenings are
committed questionnaires coded in the Tobacco Use Screening value set; the result is the
answer's response option code. Counseling is an instruction or procedure coded in the
Tobacco Use Cessation Counseling value set, or a tobacco abuse counseling (Z71.6)
diagnosis starting in the window. Pharmacotherapy is a cessation medication starting in the
window.

Measure source:
    https://ecqi.healthit.gov/ecqm/ec/2027/cms0138v15
"""

from __future__ import annotations

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import InterviewQuestionResponse
from canvas_sdk.value_set.v2027.assessment import TobaccoUseScreening
from canvas_sdk.value_set.v2027.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    NutritionServices,
    OccupationalTherapyEvaluation,
    OfficeVisit,
    OphthalmologicalServices,
    PhysicalTherapyEvaluation,
    PreventiveCareEstablishedOfficeVisit0To17,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesGroupCounseling,
    PreventiveCareServicesIndividualCounseling,
    PreventiveCareServicesInitialOfficeVisit0To17,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    Psychoanalysis,
    PsychVisitDiagnosticEvaluation,
    PsychVisitPsychotherapy,
    SpeechAndHearingEvaluation,
    TelephoneVisits,
    VirtualEncounter,
)
from canvas_sdk.value_set.v2027.intervention import TobaccoUseCessationCounseling
from canvas_sdk.value_set.v2027.medication import TobaccoUseCessationPharmacotherapy
from canvas_sdk.value_set.v2027.no_qdm_category_assigned import TobaccoNonUser, TobaccoUser

from .ecqm_common import ICD10_URL, EcqmPatient, age_in_years, billing_codes, code_filter, codes_in
from .helper_population import Population

# Health behavior assessment (96156) and intervention (96158) visits the measure names by code.
QUALIFYING_VISIT_CODES = frozenset(
    set().union(
        *(
            billing_codes(value_set)
            for value_set in (
                HomeHealthcareServices,
                OccupationalTherapyEvaluation,
                OfficeVisit,
                OphthalmologicalServices,
                PhysicalTherapyEvaluation,
                PsychVisitDiagnosticEvaluation,
                PsychVisitPsychotherapy,
                Psychoanalysis,
                SpeechAndHearingEvaluation,
                TelephoneVisits,
                VirtualEncounter,
            )
        )
    )
    | {"96156", "96158"}
)

# Unlisted preventive medicine service (99429) and postoperative follow-up (99024) by code.
PREVENTIVE_VISIT_CODES = frozenset(
    set().union(
        *(
            billing_codes(value_set)
            for value_set in (
                AnnualWellnessVisit,
                PreventiveCareServicesEstablishedOfficeVisit18AndUp,
                PreventiveCareServicesInitialOfficeVisit18AndUp,
                PreventiveCareEstablishedOfficeVisit0To17,
                PreventiveCareServicesInitialOfficeVisit0To17,
                PreventiveCareServicesGroupCounseling,
                PreventiveCareServicesIndividualCounseling,
                NutritionServices,
            )
        )
    )
    | {"99429", "99024"}
)

TOBACCO_ABUSE_COUNSELING = "Z716"  # ICD-10-CM Z71.6, stored without the dot


class ClinicalQualityMeasure138v6(ClinicalQualityMeasure):
    """CMS138v15 - Tobacco Use Screening and Cessation Intervention."""

    class Meta:
        title = (
            "Preventive Care and Screening: Tobacco Use: "
            "Screening and Cessation Intervention"
        )
        version = "2027-01-01v15"
        description = (
            "Patients aged 12 years and older who have not been screened for tobacco use "
            "during the measurement period OR who have not received tobacco cessation "
            "intervention if identified as a tobacco user."
        )
        information = "https://ecqi.healthit.gov/ecqm/ec/2027/cms0138v15"
        identifiers = ["CMS138v15"]
        types = ["CQM"]
        authors = ["American Medical Association (AMA)", "PCPI(R) Foundation (PCPI[R])"]
        references = [
            "U.S. Preventive Services Task Force. (2021). Interventions for tobacco smoking "
            "cessation in adults, including pregnant persons: US Preventive Services Task "
            "Force recommendation statement. JAMA, 325(3), 265-279.",
        ]
        show_in_chart = True
        show_in_population = False
        default_permission_flags = {
            "protocols:actions:CMS138v6:instruct": True,
            "protocols:actions:CMS138v6:interview": True,
            "protocols:actions:CMS138v6:prescribe": True,
        }

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
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
    ]

    MINIMUM_AGE = 12
    INTERVENTION_LOOKBACK_MONTHS = 6

    POPULATION_1 = "population 1"
    POPULATION_2 = "population 2"
    POPULATION_3 = "population 3"

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._populations: dict[str, Population] = {
            self.POPULATION_1: Population(),
            self.POPULATION_2: Population(),
            self.POPULATION_3: Population(),
        }

    _patient: Patient | None = None
    _ecqm: EcqmPatient | None = None
    _screening: tuple[arrow.Arrow, set[str]] | None = None
    _screening_loaded = False

    @property
    def patient(self) -> Patient:
        """The Patient row for the event target, fetched once per instance."""
        if self._patient is None:
            self._patient = Patient.objects.get(id=self.patient_id_from_target())
        return self._patient

    @property
    def ecqm(self) -> EcqmPatient:
        """eCQM data access for this patient and measurement period, built once per instance."""
        if self._ecqm is None:
            self._ecqm = EcqmPatient(
                self.patient.id, self.timeframe, age_in_years(self.patient, self.timeframe.end)
            )
        return self._ecqm

    # ----- screening -----

    @property
    def most_recent_screening(self) -> tuple[arrow.Arrow, set[str]] | None:
        """``(date, response codes)`` of the most recent tobacco screening in the period."""
        if not self._screening_loaded:
            self._screening_loaded = True
            responses = (
                InterviewQuestionResponse.objects.filter(
                    interview__patient__id=self.patient.id,
                    interview__committer__isnull=False,
                    interview__entered_in_error__isnull=True,
                    interview__deleted=False,
                    interview__questionnaires__code__in=codes_in(TobaccoUseScreening),
                    interview__created__range=(
                        self.timeframe.start.datetime,
                        self.timeframe.end.datetime,
                    ),
                )
                .exclude(response_option__isnull=True)
                .values_list("interview__id", "interview__created", "response_option__code")
            )
            by_interview: dict[object, tuple[arrow.Arrow, set[str]]] = {}
            for interview_id, created, code in responses:
                when, codes = by_interview.get(interview_id, (arrow.get(created), set()))
                by_interview[interview_id] = (when, codes | {code})
            if by_interview:
                self._screening = max(by_interview.values(), key=lambda screening: screening[0])
        return self._screening

    def _screened_as(self, results: set[str]) -> arrow.Arrow | None:
        """Date of the most recent screening when its result is in ``results``."""
        screening = self.most_recent_screening
        if screening is None or not screening[1] & results:
            return None
        return screening[0]

    @property
    def tobacco_use_screening_user(self) -> arrow.Arrow | None:
        """Date of the most recent screening, when it identified a tobacco user."""
        return self._screened_as(codes_in(TobaccoUser))

    @property
    def tobacco_use_screening_non_user(self) -> arrow.Arrow | None:
        """Date of the most recent screening, when it identified a non-user."""
        return self._screened_as(codes_in(TobaccoNonUser))

    # ----- interventions -----

    def intervention_window(self) -> Timeframe:
        """The measurement period plus the six months before it."""
        return self.ecqm.before_and_during(months=self.INTERVENTION_LOOKBACK_MONTHS)

    @property
    def tobacco_cessation_intervention_counseling(self) -> bool:
        """Cessation counseling, or a tobacco abuse counseling diagnosis, in the window."""
        window = self.intervention_window()
        if self.ecqm.has_intervention(TobaccoUseCessationCounseling, window):
            return True
        return (
            self.ecqm.conditions(code_filter(ICD10_URL, TOBACCO_ABUSE_COUNSELING), window)
            .filter(onset_date__gte=window.start.date())
            .exists()
        )

    @property
    def tobacco_cessation_intervention_medication(self) -> arrow.Arrow | None:
        """Start of the latest cessation medication started in the window."""
        starts = self.ecqm.medication_start_dates(
            TobaccoUseCessationPharmacotherapy, self.intervention_window()
        )
        return max(starts) if starts else None

    @property
    def tobacco_cessation_intervention(self) -> bool:
        """Counseling or pharmacotherapy in the window, in any order relative to the screening."""
        return bool(
            self.tobacco_cessation_intervention_counseling
            or self.tobacco_cessation_intervention_medication
        )

    # ----- populations -----

    def age_at_start(self) -> int:
        """Completed years of age at the start of the measurement period."""
        return age_in_years(self.patient, self.timeframe.start)

    def has_preventive_visit(self) -> bool:
        """At least one preventive visit in the measurement period."""
        return self.ecqm.count_visits(set(PREVENTIVE_VISIT_CODES), self.timeframe) > 0

    def count_eligible_visits(self) -> int:
        """Qualifying (non-preventive) visits in the measurement period."""
        return self.ecqm.count_visits(set(QUALIFYING_VISIT_CODES), self.timeframe)

    def in_initial_population(self) -> bool:
        """Patients 12+ at the start of the period with two qualifying visits or one preventive visit."""
        result = self.age_at_start() >= self.MINIMUM_AGE and (
            self.has_preventive_visit() or self.count_eligible_visits() >= 2
        )
        for population in self._populations.values():
            population.set_initial_population(result)
        return self._populations[self.POPULATION_3].in_initial_population

    def in_denominator(self) -> bool:
        """Populations 1 and 3 mirror the initial population; population 2 requires a positive screening.

        Patients in hospice are excluded from every population.
        """
        if self.in_initial_population() and self.ecqm.has_hospice_services():
            for population in self._populations.values():
                population.set_denominator(False)

        if (
            self._populations[self.POPULATION_2].in_denominator
            and not self.tobacco_use_screening_user
        ):
            self._populations[self.POPULATION_2].set_denominator(False)

        return self._populations[self.POPULATION_3].in_denominator

    def in_numerator(self) -> bool:
        """Each population has its own numerator rule; see the module docstring."""
        if self._populations[self.POPULATION_1].in_denominator and not (
            self.tobacco_use_screening_user or self.tobacco_use_screening_non_user
        ):
            self._populations[self.POPULATION_1].set_numerator(False)

        if (
            self._populations[self.POPULATION_2].in_denominator
            and not self.tobacco_cessation_intervention
        ):
            self._populations[self.POPULATION_2].set_numerator(False)

        if self._populations[self.POPULATION_3].in_denominator and not (
            self.tobacco_use_screening_non_user
            or (self.tobacco_use_screening_user and self.tobacco_cessation_intervention)
        ):
            self._populations[self.POPULATION_3].set_numerator(False)

        return self._populations[self.POPULATION_3].in_numerator

    # ----- cards -----

    def _build_card(self) -> ProtocolCard:
        """Build a ProtocolCard for this patient seeded with default values."""
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS138v6",
            title="Tobacco Use Screening and Cessation Intervention",
        )

    def _satisfied_card(self, occurred_on: arrow.Arrow, narrative: str) -> ProtocolCard:
        card = self._build_card()
        card.status = ProtocolCard.Status.SATISFIED
        card.narrative = narrative
        card.due_in = (occurred_on.shift(days=self.timeframe.duration) - self.now).days
        return card

    def compute(self) -> list[Effect]:
        """Return the protocol card effects for the current patient."""
        if not self.in_denominator():
            card = self._build_card()
            card.status = ProtocolCard.Status.NOT_APPLICABLE
            card.due_in = -1
            if self.age_at_start() < self.MINIMUM_AGE:
                card.due_in = (
                    arrow.get(self.patient.birth_date).shift(years=self.MINIMUM_AGE)
                    - self.timeframe.start
                ).days
            return [card.apply()]

        self.in_numerator()
        name = self.patient.first_name
        pop1 = self._populations[self.POPULATION_1]
        pop2 = self._populations[self.POPULATION_2]

        if pop2.in_denominator and not pop2.in_numerator:
            card = self._build_card()
            card.status = ProtocolCard.Status.DUE
            card.due_in = -1
            card.narrative = f"{name} is a current tobacco user, intervention is indicated."
            card.add_recommendation(
                title="Tobacco cessation counseling", button="Counsel", command="instruct"
            )
            card.add_recommendation(
                title="Cessation support medication", button="Prescribe", command="prescribe"
            )
            return [card.apply()]

        if pop1.in_denominator and not pop1.in_numerator:
            card = self._build_card()
            card.status = ProtocolCard.Status.DUE
            card.due_in = -1
            card.narrative = f"{name} should be screened for tobacco use."
            card.add_recommendation(
                title="Complete tobacco use questionnaire", button="Screen", command="interview"
            )
            return [card.apply()]

        non_user = self.tobacco_use_screening_non_user
        if non_user:
            return [
                self._satisfied_card(
                    non_user,
                    f"{name} had a Tobacco screening on {non_user.format('M/D/YY')} "
                    "and is not a tobacco user.",
                ).apply()
            ]
        screened = self.tobacco_use_screening_user or self.now
        return [
            self._satisfied_card(
                screened,
                f"{name} is a tobacco user and received a cessation intervention.",
            ).apply()
        ]
