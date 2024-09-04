# type: ignore
from typing import List

import arrow

from cached_property import cached_property

from canvas_workflow_kit import events
from canvas_workflow_kit.patient_recordset import InterviewRecordSet
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.value_set.specials import (
    Covid19QuestionnaireHighRiskOutreach,
    Covid19QuestionnaireSymptomaticSurveillance
)
from canvas_workflow_kit.value_set.v2017 import (
    ChronicObstructivePulmonaryDisease,
    ImmunocompromisedConditions,
    PersistentAsthma
)
from canvas_workflow_kit.value_set.v2019 import IschemicVascularDisease
from canvas_workflow_kit.value_set.v2020 import (
    ChronicLiverDisease,
    Diabetes,
    KidneyFailure,
    MorbidObesity
)

MINIMUM_AGE = 65


class Ccp002v1(ClinicalQualityMeasure):

    class Meta:
        title = 'COVID-19 High Risk Outreach'

        version = '2020-03-24v1'

        description = f'All patients with {MINIMUM_AGE}+ with chronic conditions to be reached.'
        information = 'https://canvas-medical.zendesk.com/hc/en-us/articles/360059084173-COVID-19-Risk-Assessment-Follow-Up-Protocol'

        identifiers = ['CCP002v1']

        types = ['CCP']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]
        show_in_chart = False

        references = [
            'Canvas Medical CCP, https://canvas-medical.zendesk.com/hc/en-us/articles/360059084173-COVID-19-Risk-Assessment-Follow-Up-Protocol'
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_CONDITION,
            ClinicalQualityMeasure.CHANGE_INTERVIEW,
            ClinicalQualityMeasure.CHANGE_PATIENT,
        ]

    @cached_property
    def date_of_first_questionnaire(self) -> str:
        questionnaire = self.patient.interviews.find(Covid19QuestionnaireSymptomaticSurveillance |
                                                     Covid19QuestionnaireHighRiskOutreach).first()
        if questionnaire:
            return questionnaire[InterviewRecordSet.DATE_FIELD]
        return ''

    @cached_property
    def high_risk_conditions(self) -> List:
        value_sets = [
            ChronicLiverDisease,
            ChronicObstructivePulmonaryDisease,
            Diabetes,
            ImmunocompromisedConditions,
            IschemicVascularDisease,
            KidneyFailure,
            MorbidObesity,
            PersistentAsthma,
        ]
        result: List = []
        for value_set in value_sets:
            result.extend([
                record for record in self.patient.conditions.find(value_set)
                if record['clinicalStatus'] == 'active'
            ])
        return result

    def in_initial_population(self) -> bool:
        """
        Patients MINIMUM_AGE+ with more than two chronic conditions
        """
        return self.patient.age >= MINIMUM_AGE or self.high_risk_conditions

    def in_denominator(self) -> bool:
        """
        Patients in the initial population
        """
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        """
        Patients that have taken one of the COVID questionnaires
        """
        return bool(self.date_of_first_questionnaire)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.due_in = -1
                result.status = STATUS_SATISFIED
                date = arrow.get(self.date_of_first_questionnaire).format('ddd, MMM Do YYYY')
                result.add_narrative(
                    f'{self.patient.first_name} took a COVID-19 outreach questionnaire on {date}.')
            else:
                result.add_narrative(
                    f'{self.patient.first_name} should take a COVID-19 outreach questionnaire.')

                if self.patient.age >= MINIMUM_AGE:
                    result.add_narrative(f'{self.patient.first_name} is {MINIMUM_AGE}+')

                if self.high_risk_conditions:
                    has_display = all(
                        [bool('display' in c['coding'][0]) for c in self.high_risk_conditions])
                    if has_display:
                        result.add_narrative(
                            f'{self.patient.first_name} has high risk conditions:')
                        for condition in self.high_risk_conditions:
                            result.add_narrative(condition['coding'][0]['display'])
                    else:
                        result.add_narrative(
                            f'{self.patient.first_name} has {len(self.high_risk_conditions)} high risk conditions'  # noqa: E501
                        )

                result.due_in = 0
                result.status = STATUS_DUE

                narrative = (f'{self.patient.first_name} should be contacted and have a '
                             'COVID-19 questionnaire administered.')
                result.add_recommendation(
                    Recommendation(
                        key='CCP002v1_RECOMMEND_QUESTIONNAIRE',
                        rank=1,
                        button='Communication',
                        title='Complete COVID-19 outreach questionnaire',
                        narrative=narrative,
                        command={'key': 'schedule'}))

        return result
