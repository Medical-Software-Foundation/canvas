from typing import Dict, List

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.timeframe import Timeframe
from canvas_workflow_kit.value_set.specials import KidneyFailure, LabReportCreatinine
from canvas_workflow_kit.value_set.v2018 import HypertensiveChronicKidneyDisease


class Hcc002v2(ClinicalQualityMeasure):

    class Meta:
        title = 'CKD suspect'

        version = '2019-02-12v1'

        description = ('All patients with evidence of two or more elevated eGFR values '
                       'and no active CKD problem on the Conditions List.')
        information = ('https://canvas-medical.zendesk.com/hc/en-us/articles/'
                       '360059083713-CKD-Suspect-HCC002v2')  # noqa: E501

        identifiers = ['HCC002v2']

        types = ['HCC']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        references = [(
            'Canvas Medical HCC, '
            'https://canvas-medical.zendesk.com/hc/en-us/articles/360059083713-CKD-Suspect-HCC002v2'  # noqa: E501
        )]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
            ClinicalQualityMeasure.CHANGE_LAB_REPORT,
            ClinicalQualityMeasure.CHANGE_PATIENT,
        ]

    @property
    def high_creatine_levels(self) -> List[Dict]:
        patient_age = int(self.patient.age_at(self.now))

        # we can't calculate an eGFR if age = 0 due to a ZeroDivisionError; we'd need to use a
        # pedatric eGFR instead (and probably should)
        if patient_age == 0:
            return []

        if self.period_adjustment:
            period = self.timeframe
        else:
            period = Timeframe(start=self.timeframe.end.shift(years=-2), end=self.timeframe.end)

        creatinine_lab_reports = (self.patient
                                  .lab_reports
                                  .find(LabReportCreatinine)
                                  .within(period))  # yapf: disable

        return [
            {
                'date': r['originalDate'],
                'value': self.eGFR(self.relative_float(r['value']), r['units']),
            }
            for r in creatinine_lab_reports
            if (self.relative_float(r['value']) > 0 and
                self.eGFR(self.relative_float(r['value']), r['units']) < 60)
        ]  # yapf: disable

    @property
    def has_active_condition(self) -> bool:
        return any(True for item in (self.patient
                                     .conditions
                                     .find(HypertensiveChronicKidneyDisease | KidneyFailure))
                   if item['clinicalStatus'] == 'active')  # yapf: disable

    def eGFR(self, creatinine: float, units: str) -> float:
        sex = 0.742 if self.patient.is_female else 1
        race = 1.210 if self.patient.is_african_american else 1
        coefficient = 1 if units == 'mg/dL' else 88.4
        return 186 * pow(creatinine / coefficient, -1.154) * pow(
            int(self.patient.age_at(self.now)), -0.203) * sex * race

    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        """
        Patients with 2*eGFR lab value of < 60 in the last 2 years
        """
        return len(self.high_creatine_levels) >= 2

    def in_numerator(self) -> bool:
        """
        Patients with no active Condition on problem list for range of ICD10 Codes
        """
        return self.has_active_condition

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    f'{self.patient.first_name} has at least two eGFR measurements < 60 ml/min '
                    'over the last two years suggesting renal disease. '
                    'There is no associated condition on the Conditions List.')
                title = ('Consider updating the Conditions List to include kidney '
                         'related problems as clinically appropriate')
                result.add_recommendation(
                    Recommendation(
                        key='HCC002v2_RECOMMEND_DIAGNOSE',
                        rank=1,
                        button='Diagnose',
                        title=title,
                        narrative=result.narrative,
                        command={'key': 'diagnose'}))
        return result
