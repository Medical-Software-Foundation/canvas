from typing import Any, List, Union

import arrow

from cached_property import cached_property

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.value_set.v2020 import Diabetes


class Ccp004v1(ClinicalQualityMeasure):

    class Meta:
        title = 'Diagnosis Of Diabetes'

        version = '2020-04-02v1'

        description = 'All patients with Diagnosis Of Diabetes.'
        information = 'https://canvas-medical.zendesk.com/hc/en-us'

        identifiers = ['CCP004v1']

        types = ['CCP']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_CONDITION,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        show_in_chart = False

        references = ['Canvas Medical CCP, https://canvas-medical.zendesk.com/hc/en-us']

    @cached_property
    def date_of_diagnosis(self) -> Union[Any, str]:
        actives: List = []
        for item in self.patient.conditions.find(Diabetes):
            actives.extend([period['from'] for period in item['periods'] if period['to'] is None])
        return min(actives) if actives else ''

    def in_initial_population(self) -> bool:
        """
        All patients
        """
        return True

    def in_denominator(self) -> bool:
        """
        Patients in the initial population
        """
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        """
        Patients that have been diagnosed with diabetes
        """
        return bool(self.date_of_diagnosis)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.due_in = 0
                result.status = STATUS_DUE
                date = arrow.get(self.date_of_diagnosis).format('ddd, MMM Do YYYY')
                narrative = f'{self.patient.first_name} has been diagnosed of diabetes on {date}.'
                result.add_narrative(narrative)
                result.add_recommendation(
                    Recommendation(
                        key='CCP004v1_RECOMMEND_CONTACT',
                        rank=1,
                        button='Communication',
                        title='Contact the patient',
                        narrative=narrative,
                        command={'key': 'schedule'}))
            else:
                result.due_in = -1
                result.status = STATUS_SATISFIED
                narrative = f'{self.patient.first_name} has not been diagnosed of diabetes.'
                result.add_narrative(narrative)

        return result
