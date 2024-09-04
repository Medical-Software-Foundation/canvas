# type: ignore
from typing import List

import arrow

from cached_property import cached_property

from canvas_workflow_kit import events
from canvas_workflow_kit.builtin_cqms.helper_population import Population
from canvas_workflow_kit.protocol import (
    CONTEXT_GUIDANCE,
    STATUS_DUE,
    STATUS_NOT_APPLICABLE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import (
    InstructionRecommendation,
    InterviewRecommendation,
    PrescribeRecommendation
)
from canvas_workflow_kit.timeframe import Timeframe
# flake8: noqa
from canvas_workflow_kit.value_set.v2018 import (
    AnnualWellnessVisit,
    Ethnicity,
    FaceToFaceInteraction,
    HealthAndBehavioralAssessmentInitial,
    HealthAndBehavioralAssessmentReassessment,
    HealthBehavioralAssessmentIndividual,
    HomeHealthcareServices,
    LimitedLifeExpectancy,
    MedicalReason,
    OccupationalTherapyEvaluation,
    OfficeVisit,
    OncAdministrativeSex,
    OphthalmologicalServices,
    Payer,
    PreventiveCareServicesEstablishedOfficeVisit18AndUp,
    PreventiveCareServicesGroupCounseling,
    PreventiveCareServicesIndividualCounseling,
    PreventiveCareServicesInitialOfficeVisit18AndUp,
    PreventiveCareServicesOther,
    Psychoanalysis,
    PsychVisitDiagnosticEvaluation,
    PsychVisitPsychotherapy,
    Race,
    SpeechAndHearingEvaluation,
    TobaccoNonUser,
    TobaccoUseCessationCounseling,
    TobaccoUseCessationPharmacotherapy,
    TobaccoUser,
    TobaccoUseScreening
)


class ClinicalQualityMeasure138v6(ClinicalQualityMeasure):
    """
    Preventive Care and Screening: Tobacco Use: Screening and Cessation Intervention

    Description: Percentage of patients aged 18 years and older who were screened for tobacco use
    one or more times within 24 months AND who received tobacco cessation intervention if
    identified as a tobacco user

    Three rates are reported:
    a. Percentage of patients aged 18 years and older who were screened for tobacco use one or more
    times within 24 months
    b. Percentage of patients aged 18 years and older who were screened for tobacco use and
    identified as a tobacco user who received tobacco cessation intervention
    c. Percentage of patients aged 18 years and older who were screened for tobacco use one or more
    times within 24 months AND who received tobacco cessation intervention if identified as a
    tobacco user

    Definition: Tobacco Use - Includes any type of tobacco
    Tobacco Cessation Intervention - Includes brief counseling (3 minutes or less), and/or
    pharmacotherapy -- Note:  Concepts aligned with brief counseling (eg, minimal and intensive
    advice/counseling interventions conducted both in person and over the phone) are included in
    the value set for the numerator.  Other concepts such as written self-help materials (eg,
    brochures, pamphlets) and complementary/alternative therapies are not included in the value set
    and do not qualify for the numerator.

    Rationale: This measure is intended to promote adult tobacco screening and tobacco cessation
    interventions for those who use tobacco products. There is good evidence that tobacco screening
    and brief cessation intervention (including counseling and/or pharmacotherapy) is successful in
    helping tobacco users quit. Tobacco users who are able to stop using tobacco lower their risk
    for heart disease, lung disease, and stroke.

    Guidance: If a patient uses any type of tobacco (ie, smokes or uses smokeless tobacco), the
    expectation is that they should receive tobacco cessation intervention: either counseling
    and/or pharmacotherapy.

    If a patient has multiple tobacco use screenings during the 24 month period, only the most
    recent screening, which has a documented status of tobacco user or tobacco non-user, will be
    used to satisfy the measure requirements.

    If tobacco use status of a patient is unknown, the patient does not meet the screening
    component required to be counted in the numerator and should be considered a measure failure.
    Instances where tobacco use status of "unknown" is recorded include: 1) the patient was not
    screened; or 2) the patient was screened and the patient (or caregiver) was unable to provide a
    definitive answer.  If the patient does not meet the screening component of the numerator but
    has an allowable medical exception, then the patient should be removed from the denominator of
    the measure and reported as a valid exception.

    The medical reason exception may be applied to either the screening data element OR to any of
    the applicable tobacco cessation intervention data elements (counseling and/or pharmacotherapy)
    included in the measure.

    If a patient has a diagnosis of limited life expectancy, that patient has a valid denominator
    exception for not being screened for tobacco use or for not receiving tobacco use cessation
    intervention (counseling and/or pharmacotherapy) if identified as a tobacco user.

    As noted above in a recommendation statement from the USPSTF, the current evidence is
    insufficient to recommend electronic nicotine delivery systems (ENDS) including electronic
    cigarettes for tobacco cessation.  Additionally, ENDS are not currently classified as tobacco
    in the recent evidence review to support the update of the USPSTF recommendation given that the
    devices do not burn or use tobacco leaves.  In light of the current lack of evidence, the
    measure does not currently capture e-cigarette usage as either tobacco use or a cessation aid.

    The requirement of "Count >=2 Encounter, Performed" is to establish that the eligible
    professional or eligible clinician has an existing relationship with the patient for certain
    types of encounters.

    This measure contains three reporting rates which aim to identify patients who were screened
    for tobacco use (rate/population 1), patients who were identified as tobacco users and who
    received tobacco cessation intervention (rate/population 2), and a comprehensive look at the
    overall performance on tobacco screening and cessation intervention (rate/population 3). By
    separating this measure into various reporting rates, the eligible professional or eligible
    clinician will be able to better ascertain where gaps in performance exist, and identify
    opportunities for improvement. The overall rate (rate/population 3) can be utilized to compare
    performance to prior published versions of this measure.

    More information: https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS138v6.html
    """

    class Meta:
        title = 'Preventive Care and Screening: Tobacco Use: Screening and Cessation Intervention'
        version = '2022-01-31v1'
        default_display_interval_in_days = 365 * 2

        description = (
            'Patients aged 18 years and older who have not been screened for tobacco use OR '
            'who have not received tobacco cessation intervention if identified as a tobacco user.'
        )
        information = 'https://ecqi.healthit.gov/sites/default/files/ecqm/measures/CMS138v6.html'

        identifiers = ['CMS138v6']

        types = ['CQM']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]

        authors = [
            'American Medical Association (AMA)',
            'PCPI(R) Foundation (PCPI[R])',
        ]

        references = [
            'Siu AL; U.S. Preventive Services Task Force. Behavioral and Pharmacotherapy Interventions for Tobacco Smoking Cessation in Adults, Including Pregnant Women: U.S. Preventive Services Task Force Recommendation Statement. Ann Intern Med. 2015 Oct 20;163(8):622-34.',
        ]
        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_BILLING_LINE_ITEM,
            ClinicalQualityMeasure.CHANGE_INSTRUCTION,
            ClinicalQualityMeasure.CHANGE_INTERVIEW,
            ClinicalQualityMeasure.CHANGE_MEDICATION,
            ClinicalQualityMeasure.CHANGE_PATIENT,
        ]

        show_in_chart = True
        show_in_population = False

    MINIMUM_AGE = 18
    POPULATION_1 = 'population 1'
    POPULATION_2 = 'population 2'
    POPULATION_3 = 'population 3'

    _populations = {
        POPULATION_1: Population(),
        POPULATION_2: Population(),
        POPULATION_3: Population(),
    }

    @cached_property
    def tobacco_cessation_intervention_counseling(self) -> arrow:
        if not self.tobacco_use_screening_user:
            return None
        # @ide-format:off
        record = (self.patient
                      .instructions
                      .within(self.timeframe)
                      .find(TobaccoUseCessationCounseling)
                      .last())  # yapf: disable
        # @ide-format:on
        if record:
            counseling = arrow.get(record['noteTimestamp'])
            if self.tobacco_use_screening_user <= counseling < self.timeframe.end:
                return counseling
        return None

    @cached_property
    def tobacco_cessation_intervention_medication(self) -> arrow:
        if not self.tobacco_use_screening_user:
            return None
        # @ide-format:off
        medication = (self.patient .medications .find(TobaccoUseCessationPharmacotherapy) .intersects(
            self.timeframe, still_active=self.patient.active_only))  # yapf: disable
        # @ide-format:on
        if medication:
            start = arrow.get(self.tobacco_use_screening_user.date())
            for item in medication.records:
                beginning = arrow.get(item['periods'][0]['from'])  # medication has only one period
                if start <= beginning < self.timeframe.end:
                    return beginning
        return None

    @cached_property
    def tobacco_cessation_intervention(self) -> bool:
        return (self.tobacco_cessation_intervention_counseling or
                self.tobacco_cessation_intervention_medication)

    @cached_property
    def assessment_not_performed(self) -> arrow:
        period = Timeframe(start=self.timeframe.start, end=self.timeframe.end)
        if not self.period_adjustment:
            period.start = period.end.shift(years=-2)
        # @ide-format:off
        record = (self.patient
                      .interviews
                      .find_question_response(MedicalReason, TobaccoUseScreening)
                      .within(period)
                      .last())  # yapf: disable
        # @ide-format:on
        return arrow.get(record['noteTimestamp']) if record else None

    @cached_property
    def counseling_not_performed(self) -> arrow:
        # @ide-format:off
        record = (self.patient
                      .interviews
                      .find_question_response(MedicalReason, TobaccoUseCessationCounseling)
                      .within(self.timeframe)
                      .last())  # yapf: disable
        # @ide-format:on
        return arrow.get(record['noteTimestamp']) if record else None

    @cached_property
    def medication_not_ordered(self) -> arrow:
        # @ide-format:off
        record = (self.patient
                      .interviews
                      .find_question_response(MedicalReason, TobaccoUseCessationPharmacotherapy)
                      .within(self.timeframe)
                      .last())  # yapf: disable
        # @ide-format:on
        return arrow.get(record['noteTimestamp']) if record else None

    @cached_property
    def tobacco_use_screening_user(self) -> arrow:
        period = Timeframe(start=self.timeframe.start, end=self.timeframe.end)
        if not self.period_adjustment:
            period.start = period.end.shift(months=-24)

        interviews = self.patient.interviews.within(period)
        screening = interviews.find(TobaccoUseScreening).last()
        user = interviews.find(TobaccoUser).last()
        return arrow.get(screening['noteTimestamp']) if screening and screening == user else None

    @cached_property
    def tobacco_use_screening_non_user(self) -> arrow:
        period = Timeframe(start=self.timeframe.start, end=self.timeframe.end)
        if not self.period_adjustment:
            period.start = period.end.shift(months=-24)

        interviews = self.patient.interviews.within(period)
        screening = interviews.find(TobaccoUseScreening).last()
        non_user = interviews.find(TobaccoNonUser).last()
        return arrow.get(
            screening['noteTimestamp']) if screening and screening == non_user else None
    
    def protocol_has_context_guidance(self) -> bool:
        if self.context == CONTEXT_GUIDANCE:
            return True

        if hasattr(self.context, 'get'):
            return True

        return False

    def in_initial_population(self) -> bool:
        """
        Initial population: All patients aged 18 years and older seen for at least two visits or at
        least one preventive visit during the measurement period
        """
        result = (self.patient.age_at(self.timeframe.end) >= self.MINIMUM_AGE and
                  (self.protocol_has_context_guidance() or
                   self.patient.has_visit_within(self.timeframe,
                                                 (AnnualWellnessVisit |
                                                  PreventiveCareServicesEstablishedOfficeVisit18AndUp |
                                                  PreventiveCareServicesGroupCounseling |
                                                  PreventiveCareServicesOther |
                                                  PreventiveCareServicesIndividualCounseling |
                                                  PreventiveCareServicesInitialOfficeVisit18AndUp))
                   or (1 < self.patient.count_visit_within(self.timeframe,
                                                           (HealthBehavioralAssessmentIndividual |
                                                            HealthAndBehavioralAssessmentInitial |
                                                            HealthAndBehavioralAssessmentReassessment |
                                                            HomeHealthcareServices |
                                                            OccupationalTherapyEvaluation |
                                                            OfficeVisit |
                                                            OphthalmologicalServices |
                                                            PsychVisitDiagnosticEvaluation |
                                                            PsychVisitPsychotherapy |
                                                            Psychoanalysis |
                                                            SpeechAndHearingEvaluation)))
                   )
                  )  # yapf: disable

        self._populations[self.POPULATION_1].set_initial_population(result)
        self._populations[self.POPULATION_2].set_initial_population(result)
        self._populations[self.POPULATION_3].set_initial_population(result)

        return self._populations[self.POPULATION_3].in_initial_population

    def in_denominator(self) -> bool:
        """
        Denominator: Population 1:
        Equals Initial Population

        Population 2:
        Equals Initial Population who were screened for tobacco use and identified as a tobacco
        user

        Population 3:
        Equals Initial Population

        Exclusions: None

        Exceptions: Population 1:
        Documentation of medical reason(s) for not screening for tobacco use (eg, limited life
        expectancy, other medical reason)

        Population 2:
        Documentation of medical reason(s) for not providing tobacco cessation intervention (eg,
        limited life expectancy, other medical reason)

        Population 3:
        Documentation of medical reason(s) for not screening for tobacco use OR for not providing
        tobacco cessation intervention for patients identified as tobacco users (eg, limited life
        expectancy, other medical reason)
        """
        self.in_initial_population()

        # population 1 --> every body is in denominator

        # population 2
        if self._populations[self.POPULATION_2].in_initial_population:
            if not self.tobacco_use_screening_user:
                self._populations[self.POPULATION_2].set_denominator(False)

        # population 3 --> every body is in denominator

        # Exclusions for when 'not action' will be identifies
        # if self._populations[self.POPULATION_1].in_initial_population:
        #     # -- limited life expectancy OR
        #     if self.assessment_not_performed:
        #         self._populations[self.POPULATION_1].set_denominator(False)
        #
        # if self._populations[self.POPULATION_2].in_initial_population:
        #     # -- limited life expectancy OR
        #     if (
        #             not self.tobacco_use_screening_user or (
        #             (
        #                     self.counseling_not_performed and
        #                     self.tobacco_use_screening_user <= self.counseling_not_performed
        #             ) or (
        #                     self.medication_not_ordered and
        #                     self.tobacco_use_screening_user <= self.medication_not_ordered
        #             ))
        #     ):
        #         self._populations[self.POPULATION_2].set_denominator(False)
        #
        # if self._populations[self.POPULATION_3].in_initial_population:
        #     # -- limited life expectancy OR
        #     if self.assessment_not_performed or (
        #             (
        #                     self.tobacco_use_screening_user and
        #                     self.counseling_not_performed and
        #                     self.tobacco_use_screening_user <= self.counseling_not_performed
        #             ) or (
        #                     self.tobacco_use_screening_user and
        #                     self.medication_not_ordered and
        #                     self.tobacco_use_screening_user <= self.medication_not_ordered
        #             )):
        #         self._populations[self.POPULATION_3].set_denominator(False)

        return self._populations[self.POPULATION_3].in_denominator

    def in_numerator(self) -> bool:
        """
        Numerator: Population 1:
        Patients who were screened for tobacco use at least once within 24 months

        Population 2:
        Patients who received tobacco cessation intervention

        Population 3:
        Patients who were screened for tobacco use at least once within 24 months AND who received
        tobacco cessation intervention if identified as a tobacco user

        Exclusions: Not Applicable
        """
        if self._populations[self.POPULATION_1].in_denominator:
            if not (self.tobacco_use_screening_user or self.tobacco_use_screening_non_user):
                self._populations[self.POPULATION_1].set_numerator(False)

        if self._populations[self.POPULATION_2].in_denominator:
            if not self.tobacco_cessation_intervention:
                self._populations[self.POPULATION_2].set_numerator(False)

        if self._populations[self.POPULATION_3].in_denominator:
            if (not self.tobacco_use_screening_non_user and
                    not (self.tobacco_use_screening_user and self.tobacco_cessation_intervention)):
                self._populations[self.POPULATION_3].set_numerator(False)

        return self._populations[self.POPULATION_3].in_numerator

    def satisfied_result(self, occurred_on: arrow, description: str, result: ProtocolResult):
        result.due_in = (occurred_on.shift(days=self.timeframe.duration) - self.now).days
        result.status = STATUS_SATISFIED
        result.add_narrative(
            description.format(name=self.patient.first_name, date=self.display_date(occurred_on)))

    def compute_results(self) -> ProtocolResult:
        """
        Clinical recommendation: The USPSTF recommends that clinicians ask all adults about tobacco
        use, advise them to stop using tobacco, and provide behavioral interventions and U.S. Food
        and Drug Administration (FDA)-approved pharmacotherapy for cessation to adults who use
        tobacco. (Grade A Recommendation) (U.S. Preventive Services Task Force, 2015)

        The USPSTF recommends that clinicians ask all pregnant women about tobacco use, advise them
        to stop using tobacco, and provide behavioral interventions for cessation to pregnant women
        who use tobacco. (Grade A Recommendation) (U.S. Preventive Services Task Force, 2015)

        The USPSTF concludes that the current evidence is insufficient to recommend electronic
        nicotine delivery systems for tobacco cessation in adults, including pregnant women. The
        USPSTF recommends that clinicians direct patients who smoke tobacco to other cessation
        interventions with established effectiveness and safety (previously stated). (Grade I
        Statement) (U.S. Preventive Services Task Force, 2015)
        """
        result = ProtocolResult()
        if self.in_denominator():
            self.in_numerator()
            if (self._populations[self.POPULATION_2].in_denominator and
                    not self._populations[self.POPULATION_2].in_numerator):
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(f'{self.patient.first_name} is a current tobacco user, '
                                     f'intervention is indicated.')
                result.add_recommendation(
                    InstructionRecommendation(
                        key='CMS138v6_RECOMMEND_CESSATION_COUNSELING',
                        rank=1,
                        button='Plan',
                        patient=self.patient,
                        instruction=TobaccoUseCessationCounseling,
                        title='Tobacco cessation counseling'))
                result.add_recommendation(
                    PrescribeRecommendation(
                        key='CMS138v6_RECOMMEND_CESSATION_MEDICATION',
                        rank=2,
                        button='Plan',
                        patient=self.patient,
                        prescription=TobaccoUseCessationPharmacotherapy,
                        title='Cessation support medication'))

            elif (self._populations[self.POPULATION_1].in_denominator and
                  not self._populations[self.POPULATION_1].in_numerator):
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    f'{self.patient.first_name} should be screened for tobacco use.')
                result.add_narrative(self.screening_interval_context())
                result.add_recommendation(
                    InterviewRecommendation(
                        key='CMS138v6_RECOMMEND_TOBACCO_USE_SCREENING',
                        rank=1,
                        button='Plan',
                        patient=self.patient,
                        questionnaires=[TobaccoUseScreening],
                        title='Complete tobacco use questionnaire'))

            elif self.tobacco_use_screening_non_user:
                self.satisfied_result(
                    self.tobacco_use_screening_non_user,
                    '{name} had a Tobacco screening {date} and is not a smoker.', result)
            elif self.tobacco_cessation_intervention_counseling:
                self.satisfied_result(self.tobacco_cessation_intervention_counseling,
                                      '{name} had a smoking cessation counseling {date}.', result)
            elif self.tobacco_cessation_intervention_medication:
                self.satisfied_result(self.tobacco_cessation_intervention_medication,
                                      '{name} has been prescribed cessation medication {date}.',
                                      result)
        elif self.patient.age_at(self.timeframe.end) < self.MINIMUM_AGE:
            result.status = STATUS_NOT_APPLICABLE
            result.due_in = (
                self.patient.birthday.shift(years=self.MINIMUM_AGE) - self.timeframe.end).days
        return result
