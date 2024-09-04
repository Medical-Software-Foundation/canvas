from typing import Dict, List

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
from canvas_workflow_kit.value_set.hcc2018 import HCCConditions


class Hcc001v1(ClinicalQualityMeasure):

    class Meta:
        title = 'Problem List Hygiene'
        version = '2019-02-12v1'
        description = 'All patients with active condition not assessed within the last year.'
        information = 'https://canvas-medical.zendesk.com/hc/en-us/articles/360059083693-Problem-List-Hygiene-HCC001v1'  # noqa: E501

        identifiers = ['HCC001v1']

        types = ['HCC']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        references = [
            'Canvas Medical HCC, https://canvas-medical.zendesk.com/hc/en-us/articles/360059083693-Problem-List-Hygiene-HCC001v1'  # noqa: E501
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
        ]

    @cached_property
    def active_hcc(self) -> List[Dict]:
        hcc_conditions = []
        for record in [
                r for r in self.patient.conditions.find(HCCConditions)
                if r['clinicalStatus'] == 'active'
        ]:
            if record['lastTimestamps']['assessed']:
                last_date = arrow.get(record['lastTimestamps']['assessed'])
            else:
                last_date = arrow.get(record['noteTimestamp'])

            codes = [c for c in record['coding'] if c['system'] == 'ICD-10']
            if codes:
                hcc_conditions.append({
                    'ICD10': codes[0]['code'],
                    'date': last_date,
                })
        return hcc_conditions

    @cached_property
    def too_old_hccs(self) -> List:
        return [hcc for hcc in self.active_hcc if hcc['date'] < self.timeframe.start]

    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        """
        Patients with active condition in the HCC list
        """
        return bool(self.active_hcc)

    def in_numerator(self) -> bool:
        """
        Patients with active condition in the HCC list
         did not have a prior assessment or diagnosis in past 12 months
        """
        return bool(self.too_old_hccs)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.due_in = -1
                result.status = STATUS_DUE
                for hcc in self.too_old_hccs:
                    idc10 = hcc['ICD10']
                    label = HCCConditions.label_idc10_for(idc10)
                    raf = HCCConditions.raf_for(idc10)
                    day = hcc['date'].format('M/D/YY')
                    result.add_narrative(
                        f'{label} ({idc10}) is a significant condition which should be assessed annually. '  # noqa: E501
                        f'The condition was last assessed on {day} and carries a RAF value of {raf}'
                    )

                result.add_recommendation(
                    Recommendation(
                        key='HCC001v1_RECOMMEND_ASSESS_CONDITION',
                        rank=1,
                        button='Assess',
                        title='Assess, update or resolve conditions as clinically appropriate',
                        narrative=(
                            '{0} has un-assessed HCC conditions for more than one year'.format(
                                self.patient.first_name)),
                        command={'key': 'assess'}))
                result.add_recommendation(
                    Recommendation(
                        key='HCC001v1_RECOMMEND_RESOLVE_CONDITION',
                        rank=2,
                        button='Assess',
                        title='Resolve conditions as clinically appropriate',
                        narrative=(
                            '{0} has un-assessed HCC conditions for more than one year'.format(
                                self.patient.first_name)),
                        command={'key': 'resolveCondition'}))
            else:
                result.due_in = (min([hcc['date'] for hcc in self.active_hcc
                                      ]).shift(days=self.timeframe.duration) - self.now).days
                result.status = STATUS_SATISFIED
                result.add_narrative('All Significant Condition have been assessed within the last {0}.'.format(  # noqa: E501
                    self.now.shift(months=-1, days=-1 * self.timeframe.duration)
                        .humanize(other=self.now, granularity='month', only_distance=True)
                ).replace(' ago', ''))  # yapf: disable
        return result
