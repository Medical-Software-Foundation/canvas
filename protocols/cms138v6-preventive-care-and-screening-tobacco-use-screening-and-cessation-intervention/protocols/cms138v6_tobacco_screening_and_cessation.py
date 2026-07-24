"""CMS138v6 - Preventive Care and Screening: Tobacco Use: Screening and Cessation Intervention.

Three-population clinical quality measure that screens adults for tobacco use
within the past 24 months and recommends cessation counseling and/or
pharmacotherapy for current tobacco users.

Populations:
    - Population 1: adults screened for tobacco use within 24 months.
    - Population 2: adults identified as tobacco users who received a cessation
      intervention (counseling or pharmacotherapy).
    - Population 3: composite of Populations 1 and 2.

Initial population requirement (any of):
    - One eligible preventive visit in the timeframe, or
    - At least two eligible non-preventive encounters in the timeframe.

Measure source:
    https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS138v6.html
"""

from functools import cached_property

import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.protocol_card import ProtocolCard
from canvas_sdk.events import EventType
from canvas_sdk.protocols import ClinicalQualityMeasure
from canvas_sdk.protocols.timeframe import Timeframe
from canvas_sdk.v1.data.billing import BillingLineItem
from canvas_sdk.v1.data.instruction import Instruction
from canvas_sdk.v1.data.medication import Medication
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.questionnaire import Interview
from canvas_sdk.value_set.v2022.assessment import TobaccoUseScreening
from canvas_sdk.value_set.v2022.encounter import (
    AnnualWellnessVisit,
    HomeHealthcareServices,
    OccupationalTherapyEvaluation,
    OfficeVisit,
    OphthalmologicalServices,
    PreventiveCareServicesEstablishedOfficeVisit_18AndUp,
    PreventiveCareServicesGroupCounseling,
    PreventiveCareServicesIndividualCounseling,
    PreventiveCareServicesInitialOfficeVisit_18AndUp,
    PreventiveCareServicesOther,
    Psychoanalysis,
    PsychVisitDiagnosticEvaluation,
    PsychVisitPsychotherapy,
    SpeechAndHearingEvaluation,
)
from canvas_sdk.value_set.v2022.intervention import TobaccoUseCessationCounseling
from canvas_sdk.value_set.v2022.medication import TobaccoUseCessationPharmacotherapy
from canvas_sdk.value_set.v2026.no_qdm_category_assigned import TobaccoNonUser, TobaccoUser
from canvas_sdk.value_set.value_set import ValueSet

from .helper_population import Population


class HealthBehavioralAssessmentIndividual(ValueSet):
    """Health and Behavioral Assessment - Individual (eCQM v2018).

    Ported from canvas_workflow_kit's v2018 value set; not present in the SDK
    value-set distribution.
    """

    VALUE_SET_NAME = "Health & Behavioral Assessment - Individual"
    OID = "2.16.840.1.113883.3.526.3.1020"
    CPT = {"96152"}


class HealthAndBehavioralAssessmentInitial(ValueSet):
    """Health and Behavioral Assessment - Initial (eCQM v2018).

    Ported from canvas_workflow_kit's v2018 value set.
    """

    VALUE_SET_NAME = "Health and Behavioral Assessment - Initial"
    OID = "2.16.840.1.113883.3.526.3.1245"
    CPT = {"96150"}


class HealthAndBehavioralAssessmentReassessment(ValueSet):
    """Health and Behavioral Assessment - Reassessment (eCQM v2018).

    Ported from canvas_workflow_kit's v2018 value set.
    """

    VALUE_SET_NAME = "Health and Behavioral Assessment, Reassessment"
    OID = "2.16.840.1.113883.3.526.3.1529"
    CPT = {"96151"}


PREVENTIVE_VISITS = (
    AnnualWellnessVisit
    | PreventiveCareServicesEstablishedOfficeVisit_18AndUp
    | PreventiveCareServicesGroupCounseling
    | PreventiveCareServicesOther
    | PreventiveCareServicesIndividualCounseling
    | PreventiveCareServicesInitialOfficeVisit_18AndUp
)

OTHER_ELIGIBLE_VISITS = (
    HealthBehavioralAssessmentIndividual
    | HealthAndBehavioralAssessmentInitial
    | HealthAndBehavioralAssessmentReassessment
    | HomeHealthcareServices
    | OccupationalTherapyEvaluation
    | OfficeVisit
    | OphthalmologicalServices
    | PsychVisitDiagnosticEvaluation
    | PsychVisitPsychotherapy
    | Psychoanalysis
    | SpeechAndHearingEvaluation
)

LOINC_URL = "http://loinc.org"
SNOMEDCT_URL = "http://snomed.info/sct"


class ClinicalQualityMeasure138v6(ClinicalQualityMeasure):
    """CMS138v6 - Tobacco Use Screening and Cessation Intervention."""

    class Meta:
        title = (
            "Preventive Care and Screening: Tobacco Use: "
            "Screening and Cessation Intervention"
        )
        version = "2022-01-31v1"
        description = (
            "Patients aged 18 years and older who have not been screened for "
            "tobacco use OR who have not received tobacco cessation intervention "
            "if identified as a tobacco user."
        )
        information = "https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS138v6.html"
        identifiers = ["CMS138v6"]
        types = ["CQM"]
        authors = ["American Medical Association (AMA)", "PCPI(R) Foundation (PCPI[R])"]
        references = [
            "Siu AL; U.S. Preventive Services Task Force. Behavioral and "
            "Pharmacotherapy Interventions for Tobacco Smoking Cessation in "
            "Adults, Including Pregnant Women: U.S. Preventive Services Task "
            "Force Recommendation Statement. Ann Intern Med. 2015 Oct 20;163(8):622-34.",
        ]
        show_in_chart = True
        show_in_population = False
        default_permission_flags = {
            "protocols:actions:CMS138v6:instruct": True,
            "protocols:actions:CMS138v6:interview": True,
            "protocols:actions:CMS138v6:prescribe": True,
        }

    RESPONDS_TO = [
        EventType.Name(EventType.PATIENT_CREATED),
        EventType.Name(EventType.PATIENT_UPDATED),
        EventType.Name(EventType.CONDITION_CREATED),
        EventType.Name(EventType.MEDICATION_LIST_ITEM_CREATED),
        EventType.Name(EventType.BILLING_LINE_ITEM_CREATED),
        EventType.Name(EventType.INTERVIEW_CREATED),
        EventType.Name(EventType.INSTRUCTION_CREATED),
        EventType.Name(EventType.INSTRUCTION_UPDATED),
    ]

    MINIMUM_AGE = 18
    SCREENING_LOOKBACK_MONTHS = 24

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

    @cached_property
    def patient(self) -> Patient:
        """The Patient row for the event target."""
        return Patient.objects.get(id=self._resolve_patient_id())

    def _resolve_patient_id(self) -> str:
        """Patient id for the current event.

        Falls back to ``event.context['patient_id']`` for event types
        (e.g. INTERVIEW_CREATED) that
        ``ClinicalQualityMeasure.patient_id_from_target`` does not handle.
        """
        if self._patient_id:
            return self._patient_id

        try:
            return self.patient_id_from_target()
        except ValueError:
            patient_id = self.event.context.get("patient_id") if self.event.context else None
            if not patient_id:
                raise
            self._patient_id = patient_id
            return patient_id

    @cached_property
    def screening_timeframe(self) -> Timeframe:
        """Timeframe used to find tobacco screening interviews (24 months ending now)."""
        return Timeframe(start=self.now.shift(months=-self.SCREENING_LOOKBACK_MONTHS), end=self.now)

    @cached_property
    def _screening_interviews(self) -> list[Interview]:
        """Committed tobacco screening interviews for the patient within the lookback.

        Note: filters on ``Interview.created`` since the SDK ``Interview`` model
        exposes ``note_id`` as a plain integer field, not a relation, so we
        cannot ``__range`` filter on the note's ``datetime_of_service``.
        """
        return list(
            Interview.objects.for_patient(self.patient.id)
            .committed()
            .filter(
                questionnaires__code_system=LOINC_URL,
                questionnaires__code__in=TobaccoUseScreening.values.get("LOINC", set()),
                created__range=(
                    self.screening_timeframe.start.datetime,
                    self.screening_timeframe.end.datetime,
                ),
            )
            .order_by("-created")
            .distinct()
        )

    def _latest_screening_with_response(
        self, response_codes: set[str]
    ) -> arrow.Arrow | None:
        for interview in self._screening_interviews:
            matching = interview.interview_responses.filter(
                response_option__code__in=response_codes,
            ).exists()
            if matching:
                return arrow.get(interview.created)
        return None

    @cached_property
    def tobacco_use_screening_user(self) -> arrow.Arrow | None:
        """Most recent screening where the patient was identified as a tobacco user."""
        return self._latest_screening_with_response(
            TobaccoUser.values.get("SNOMEDCT", set())
        )

    @cached_property
    def tobacco_use_screening_non_user(self) -> arrow.Arrow | None:
        """Most recent screening where the patient was identified as a non-user."""
        return self._latest_screening_with_response(
            TobaccoNonUser.values.get("SNOMEDCT", set())
        )

    @cached_property
    def tobacco_cessation_intervention_counseling(self) -> arrow.Arrow | None:
        """Cessation counseling instruction recorded after a positive screening."""
        screening_at = self.tobacco_use_screening_user
        if not screening_at:
            return None

        instruction = (
            Instruction.objects.for_patient(self.patient.id)
            .committed()
            .find(TobaccoUseCessationCounseling)
            .filter(
                note__datetime_of_service__gte=screening_at.datetime,
                note__datetime_of_service__lt=self.timeframe.end.datetime,
            )
            .order_by("note__datetime_of_service")
            .first()
        )
        if not instruction:
            return None
        return arrow.get(instruction.note.datetime_of_service)

    @cached_property
    def tobacco_cessation_intervention_medication(self) -> arrow.Arrow | None:
        """Active cessation pharmacotherapy started after a positive screening."""
        screening_at = self.tobacco_use_screening_user
        if not screening_at:
            return None

        medications = (
            Medication.objects.for_patient(self.patient.id)
            .committed()
            .find(TobaccoUseCessationPharmacotherapy)
            .filter(status="active")
            .order_by("start_date")
        )

        screening_date = arrow.get(screening_at.date())
        for medication in medications:
            if not medication.start_date:
                continue
            start = arrow.get(medication.start_date)
            if screening_date <= start < self.timeframe.end:
                return start
        return None

    @cached_property
    def tobacco_cessation_intervention(self) -> bool:
        """True when either counseling or pharmacotherapy followed a positive screening."""
        return bool(
            self.tobacco_cessation_intervention_counseling
            or self.tobacco_cessation_intervention_medication
        )

    def _visit_queryset(self, value_set: type[ValueSet]):  # type: ignore[no-untyped-def]
        return (
            BillingLineItem.objects.filter(patient__id=self.patient.id)
            .find(value_set)
            .within(self.timeframe)
        )

    def has_preventive_visit(self) -> bool:
        """True if the patient has at least one preventive visit in the timeframe."""
        return self._visit_queryset(PREVENTIVE_VISITS).exists()

    def count_eligible_visits(self) -> int:
        """Number of non-preventive eligible visits in the timeframe."""
        return self._visit_queryset(OTHER_ELIGIBLE_VISITS).count()

    def in_initial_population(self) -> bool:
        """All adults with one preventive visit or at least two other eligible visits."""
        result = self.patient.age_at(self.timeframe.end) >= self.MINIMUM_AGE and (
            self.has_preventive_visit() or self.count_eligible_visits() > 1
        )

        self._populations[self.POPULATION_1].set_initial_population(result)
        self._populations[self.POPULATION_2].set_initial_population(result)
        self._populations[self.POPULATION_3].set_initial_population(result)

        return self._populations[self.POPULATION_3].in_initial_population

    def in_denominator(self) -> bool:
        """Populations 1 and 3 mirror the initial population; population 2 requires a positive screening."""
        self.in_initial_population()

        if (
            self._populations[self.POPULATION_2].in_initial_population
            and not self.tobacco_use_screening_user
        ):
            self._populations[self.POPULATION_2].set_denominator(False)

        return self._populations[self.POPULATION_3].in_denominator

    def in_numerator(self) -> bool:
        """Each population has its own numerator rule; see class docstring."""
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

    def _build_card(self) -> ProtocolCard:
        """Build a ProtocolCard for this patient seeded with default values."""
        return ProtocolCard(
            patient_id=self.patient.id,
            key="CMS138v6",
            title="Tobacco Use Screening and Cessation Intervention",
        )

    def _satisfied_card(self, occurred_on: arrow.Arrow, narrative_template: str) -> ProtocolCard:
        card = self._build_card()
        card.status = ProtocolCard.Status.SATISFIED
        card.narrative = narrative_template.format(
            name=self.patient.first_name,
            date=occurred_on.format("M/D/YY"),
        )
        card.due_in = (occurred_on.shift(days=self.timeframe.duration) - self.now).days
        return card

    def compute(self) -> list[Effect]:
        """Return the protocol card effects for the current patient."""
        if self.patient.age_at(self.timeframe.end) < self.MINIMUM_AGE:
            card = self._build_card()
            card.status = ProtocolCard.Status.NOT_APPLICABLE
            card.due_in = (
                arrow.get(self.patient.birth_date).shift(years=self.MINIMUM_AGE)
                - self.timeframe.end
            ).days
            return [card.apply()]

        if not self.in_denominator():
            return []

        self.in_numerator()

        pop1 = self._populations[self.POPULATION_1]
        pop2 = self._populations[self.POPULATION_2]

        if pop2.in_denominator and not pop2.in_numerator:
            card = self._build_card()
            card.status = ProtocolCard.Status.DUE
            card.due_in = -1
            card.narrative = (
                f"{self.patient.first_name} is a current tobacco user, "
                "intervention is indicated."
            )
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
            card.narrative = f"{self.patient.first_name} should be screened for tobacco use."
            card.add_recommendation(
                title="Complete tobacco use questionnaire", button="Screen", command="interview"
            )
            return [card.apply()]

        # Patient satisfies the measure; pick the most informative narrative.
        for occurred_on, narrative in (
            (
                self.tobacco_use_screening_non_user,
                "{name} had a Tobacco screening on {date} and is not a smoker.",
            ),
            (
                self.tobacco_cessation_intervention_counseling,
                "{name} had a smoking cessation counseling on {date}.",
            ),
            (
                self.tobacco_cessation_intervention_medication,
                "{name} has been prescribed cessation medication on {date}.",
            ),
        ):
            if occurred_on:
                return [self._satisfied_card(occurred_on, narrative).apply()]

        return []
