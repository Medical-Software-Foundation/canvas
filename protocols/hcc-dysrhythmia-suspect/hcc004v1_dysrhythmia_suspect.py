from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.value_set.medication_class_path2018 import Antiarrhythmics
from canvas_workflow_kit.value_set.specials import DysrhythmiaClassConditionSuspect


class Hcc004v1(ClinicalQualityMeasure):

    class Meta:
        title = 'Dysrhythmia Suspects'
        version = '2019-02-12v1'
        description = ('All patients with potential dysrhythmia based on an '
                       'active medication without associated active problem.')
        information = 'https://canvas-medical.zendesk.com/hc/en-us/articles/360059083773-Dysrhythmia-Suspects-HCC004v1'  # noqa: E501

        identifiers = ['HCC004v1']

        types = ['HCC']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        references = [
            'Canvas Medical HCC, https://canvas-medical.zendesk.com/hc/en-us/articles/360059083773-Dysrhythmia-Suspects-HCC004v1'  # noqa: E501
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
            ClinicalQualityMeasure.CHANGE_MEDICATION,
        ]

    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        """
        Patients with any active medication in Antiarrhythmics Drug Class
        """
        if self.patient.medications.find(Antiarrhythmics).intersects(
                self.timeframe, still_active=self.patient.active_only):
            return True
        return False

    def in_numerator(self) -> bool:
        """
        Patients without active conditions within the list with ICD 10 I42.* I47.*, I48.*, I49.*
        """
        if (self.patient.conditions
                        .intersects(self.timeframe, still_active=self.patient.active_only)
                        .find_class(DysrhythmiaClassConditionSuspect)):  # yapf: disable
            return False
        return True

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative((
                    '{0} has an active medication on the Medication List commonly used for Dysrhythmia. '  # noqa: E501
                    'There is no associated condition on the Conditions List.').format(
                        self.patient.first_name))
                title = ('Consider updating the Conditions List to include Dysrhythmia '
                         'related problem as clinically appropriate.')
                result.add_recommendation(
                    Recommendation(
                        key='HCC004v1_RECOMMEND_DIAGNOSE_DYSRHYTHMIA',
                        rank=1,
                        button='Diagnose',
                        title=title,
                        narrative=result.narrative,
                        command={'key': 'diagnose'}))
            else:
                result.status = STATUS_SATISFIED
        return result
