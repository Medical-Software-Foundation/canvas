from typing import Dict, List

from canvas_workflow_kit import events
from canvas_workflow_kit.canvas_code_set import CanvasCodeSet
from canvas_workflow_kit.intervention import Intervention
from canvas_workflow_kit.patient_recordset import InterviewRecordSet
from canvas_workflow_kit.protocol import STATUS_DUE, STATUS_SATISFIED, ClinicalQualityMeasure, ProtocolResult
from canvas_workflow_kit.recommendation import (
    Recommendation, ImmunizationRecommendation
)
from canvas_workflow_kit.timeframe import Timeframe
from canvas_workflow_kit.value_set.specials import (
    Covid19QuestionnaireHighRiskOutreach,
    Covid19QuestionnaireSymptomaticSurveillance
)


from canvas_workflow_kit.value_set.v2018 import (
    InfluenzaVaccine_1254
)

# flake8: noqa


class HyperlinkRecommendation(ClinicalQualityMeasure):

    class Meta:
        title = 'Hyperlink Recommendation'
        version = "1.2"
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

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()

        result.add_recommendation(
            Intervention(
                title='Link Rec Title',
                narrative=f'Link Rec Narr',
                href='http://canvasmedical.com'
            )
        )
        result.add_recommendation(
            ImmunizationRecommendation(
                key='KEY-ID',
                rank=123,
                button='ACT',
                patient=self.patient,
                immunization=InfluenzaVaccine_1254)
        )

        return result
