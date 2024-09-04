# type: ignore
from typing import Dict, List

import arrow

from cached_property import cached_property

from canvas_workflow_kit import events
from canvas_workflow_kit.canvas_code_set import CanvasCodeSet
from canvas_workflow_kit.patient_recordset import InterviewRecordSet
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.timeframe import Timeframe
from canvas_workflow_kit.value_set.specials import (
    Covid19QuestionnaireHighRiskOutreach,
    Covid19QuestionnaireSymptomaticSurveillance
)


# flake8: noqa
class Ccp001v1(ClinicalQualityMeasure):

    class Meta:

        title = 'COVID-19 Risk Assessment Follow Up'
        version = "2020-04-03v1"
        changelog = "Initial release"

        description = 'All patients with COVID Questionnaire completed Date < 7 days ago and >  5 days ago.'
        information = 'https://canvas-medical.zendesk.com/hc/en-us/articles/360059084173-COVID-19-Risk-Assessment-Follow-Up-Protocol'

        identifiers = ['CCP001v1']

        types = ['CCP']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_INTERVIEW,
        ]

        references = [
            'Canvas Medical CCP, https://canvas-medical.zendesk.com/hc/en-us/articles/360059084173-COVID-19-Risk-Assessment-Follow-Up-Protocol'
        ]

        show_in_chart = False

    anchor_format = 'YYYY-MM-DD 12:00:00ZZ'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rationales_for_inclusion_in_numerator: List = []

    @cached_property
    def anchor_time(self) -> arrow:
        # regardless of the time of the day at the practice
        # the anchor time is set at the middle of day at the practice
        # all questionnaires from 12 of D-1 to 12 D will be considered on day D
        timezone = 'UTC'
        if 'timezone' in self.patient.patient:
            timezone = self.patient.patient['timezone']
        return arrow.get(self.timeframe.end.to(timezone).format(self.anchor_format)).to('utc')

    @cached_property
    def interview(self) -> Dict:
        start = self.anchor_time.shift(days=-6)
        period = Timeframe(start=start, end=self.anchor_time)
        return (self.patient.interviews.find(Covid19QuestionnaireSymptomaticSurveillance |
                                             Covid19QuestionnaireHighRiskOutreach).within(period).
                first() or {})

    def in_initial_population(self) -> bool:
        """
        Patients with COVID Questionnaire completed Date < 7 days ago
        """
        return bool(self.interview)

    def in_denominator(self) -> bool:
        """
        Patients with COVID Questionnaire completed 6 days ago
        """
        if not self.in_initial_population():
            return False

        start = self.anchor_time.shift(days=-6)
        end = start.shift(days=1)
        interview_date = arrow.get(self.interview[InterviewRecordSet.DATE_FIELD])
        return bool(start <= interview_date < end)

    def in_numerator(self) -> bool:
        """
        Patients that need a follow up
        """
        follow_up_question = CanvasCodeSet.code('CANVAS0005')
        follow_up_response = '183616001'
        symptom_question = CanvasCodeSet.code('CANVAS0002')
        travel_question = CanvasCodeSet.code('CANVAS0003')
        travel_response = '276030007'
        exposure_question = CanvasCodeSet.code('CANVAS0004')
        exposure_response = '150781000119103'

        result = False
        interview = self.interview
        if interview:
            question_responses = self.group_question_responses(interview)
            answers = {r['code']: r['value'] for r in interview['responses']}

            for question, responses in question_responses.items():
                rationale = ''
                if question == follow_up_question and follow_up_response in responses:
                    rationale = 'Follow-up requested by care team'
                elif question == symptom_question:
                    rationale = f'Symptoms exhibited: {", ".join([answers[c] for c in responses])}'

                if rationale:
                    result = True
                    self.rationales_for_inclusion_in_numerator.append(rationale)

            # Recent travel or recent exposure can only be a primary inclusion criteria if the patient is 65+.
            # If younger, it will be included as context along with other primary inclusion criteria.
            follow_up = result
            for question, responses in question_responses.items():
                rationale = ''
                if question == travel_question and travel_response in responses:
                    if follow_up:
                        rationale = 'Recent travel'
                    elif self.patient.age_at(self.anchor_time) >= 65:
                        rationale = 'Age 65+ with recent travel'
                elif question == exposure_question and exposure_response in responses:
                    if follow_up:
                        rationale = 'Recent exposure'
                    elif self.patient.age_at(self.anchor_time) >= 65:
                        rationale = 'Age 65+ with recent exposure'

                if rationale:
                    result = True
                    self.rationales_for_inclusion_in_numerator.append(rationale)

        return result

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            result.due_in = -1
            result.next_review = arrow.utcnow().shift(days=1)
            if self.in_numerator():
                result.status = STATUS_DUE
                result.add_narrative(f'{self.patient.first_name} should have a follow-up arranged')
                for rationale in self.rationales_for_inclusion_in_numerator:
                    result.add_narrative(rationale)

                result.add_recommendation(
                    Recommendation(
                        key='CCP001v1_RECOMMEND_FOLLOW_UP',
                        rank=1,
                        button='Communication',
                        title='Arrange a follow-up',
                        narrative=f'{self.patient.first_name} should have a follow-up arranged',
                        command={'key': 'schedule'}))
            else:
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    f'{self.patient.first_name} does not need a follow-up arranged')
        elif self.in_initial_population():
            result.due_in = 5 - (
                arrow.utcnow() - arrow.get(self.interview[InterviewRecordSet.DATE_FIELD])).days

            now_local = arrow.utcnow().to(self.patient.patient['timezone'])
            tomorrow_noon = arrow.get(now_local.format(self.anchor_format))
            sometime_after_noon = tomorrow_noon.shift(days=1, hours=1)
            result.next_review = sometime_after_noon.to('utc')

        return result
