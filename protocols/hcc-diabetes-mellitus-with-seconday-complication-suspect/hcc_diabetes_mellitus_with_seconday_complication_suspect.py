# type: ignore
from typing import Type

from cached_property import cached_property

from canvas_workflow_kit import events
from canvas_workflow_kit.protocol import (
    STATUS_DUE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult
)
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.value_set.specials import (
    DiabetesCirculatoryClassConditionSuspect,
    DiabetesEyeClassConditionSuspect,
    DiabetesEyeConditionSuspect,
    DiabetesNeurologicConditionSuspect,
    DiabetesOtherClassConditionSuspect,
    DiabetesRenalConditionSuspect,
    DiabetesWithoutComplication
)
from canvas_workflow_kit.value_set.value_set import ValueSet


class Hcc003v1(ClinicalQualityMeasure):

    class Meta:
        title = 'Diabetes Mellitus With Secondary Complication Suspect'
        version = '2019-02-12v1'
        description = 'All patients with diabetes, uncomplicated AND a 2ndary condition often associated with diabetes.'  # noqa: E501
        information = 'https://canvas-medical.zendesk.com/hc/en-us/articles/360057221174-Diabetes-Mellitus-With-Secondary-Complication-Suspect-HCC003v1'  # noqa: E501

        identifiers = ['HCC003v1']

        types = ['HCC']

        responds_to_event_types = [
            events.HEALTH_MAINTENANCE,
        ]
        authors = [
            'Canvas Medical Team',
        ]

        references = [
            'Canvas Medical HCC, https://canvas-medical.zendesk.com/hc/en-us/articles/360057221174-Diabetes-Mellitus-With-Secondary-Complication-Suspect-HCC003v1'  # noqa: E501
        ]

        compute_on_change_types = [
            ClinicalQualityMeasure.CHANGE_PROTOCOL_OVERRIDE,
            ClinicalQualityMeasure.CHANGE_CONDITION,
        ]

    def _has_active_condition(self, conditions: Type[ValueSet]) -> bool:
        if self.patient.conditions.intersects(
                self.timeframe, still_active=self.patient.active_only).find(conditions):
            return True
        return False

    def _has_active_class_condition(self, class_conditions: Type[ValueSet]) -> bool:
        if (self.patient.conditions
                        .intersects(self.timeframe, still_active=self.patient.active_only)
                        .find_class(class_conditions)):  # yapf: disable
            return True
        return False

    @property
    def has_diabetes_with_unspecified_condition(self) -> bool:
        return self._has_active_condition(DiabetesWithoutComplication)

    @cached_property
    def has_suspect_eye_condition(self) -> bool:
        return (self._has_active_condition(DiabetesEyeConditionSuspect) |
                self._has_active_class_condition(DiabetesEyeClassConditionSuspect))

    @cached_property
    def has_suspect_neurologic_condition(self) -> bool:
        return self._has_active_condition(DiabetesNeurologicConditionSuspect)

    @cached_property
    def has_suspect_renal_condition(self) -> bool:
        return self._has_active_condition(DiabetesRenalConditionSuspect)

    @cached_property
    def has_suspect_circulatory_condition(self) -> bool:
        return self._has_active_class_condition(DiabetesCirculatoryClassConditionSuspect)

    @cached_property
    def has_suspect_other_condition(self) -> bool:
        return self._has_active_class_condition(DiabetesOtherClassConditionSuspect)

    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        """
        Patients with active condition E11.9 Diabetes 2 with unspecified complications
        """
        return self.has_diabetes_with_unspecified_condition

    def in_numerator(self) -> bool:
        """
        Patients with active Conditions as potential Diabetes complication
        """
        return (self.has_suspect_eye_condition or self.has_suspect_neurologic_condition or
                self.has_suspect_renal_condition or self.has_suspect_circulatory_condition or
                self.has_suspect_other_condition)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.due_in = -1
                result.status = STATUS_DUE

                if self.has_suspect_eye_condition:
                    comment = (
                        '{0} has Diabetes without complications AND '
                        'an eye condition commonly caused by diabetes on the Conditions list.'
                    ).format(self.patient.first_name)
                    title = ('Consider updating the Diabetes without complications (E11.9) '
                             'to Diabetes with secondary eye disease as clinically appropriate.')
                    result.add_narrative(comment)
                    result.add_recommendation(
                        Recommendation(
                            key='HCC003v1_RECOMMEND_DIAGNOSE_EYE',
                            rank=1,
                            button='Diagnose',
                            title=title,
                            narrative=comment,
                            command={'key': 'diagnose'}))

                if self.has_suspect_neurologic_condition:
                    comment = (
                        '{0} has Diabetes without complications AND '
                        'a neurological condition commonly caused by diabetes on the Conditions list.'  # noqa: E501
                    ).format(self.patient.first_name)
                    title = (
                        'Consider updating the Diabetes without complications (E11.9) '
                        'to Diabetes with secondary neurological sequela as clinically appropriate.'
                    )
                    result.add_narrative(comment)
                    result.add_recommendation(
                        Recommendation(
                            key='HCC003v1_RECOMMEND_DIAGNOSE_NEUROLOGICAL_SEQUELA',
                            rank=2,
                            button='Diagnose',
                            title=title,
                            narrative=comment,
                            command={'key': 'diagnose'}))

                if self.has_suspect_renal_condition:
                    comment = (
                        '{0} has Diabetes without complications AND '
                        'a chronic renal condition commonly caused by diabetes on the Conditions list.'  # noqa: E501
                    ).format(self.patient.first_name)
                    title = ('Consider updating the Diabetes without complications (E11.9) '
                             'to Diabetes with secondary renal disease as clinically appropriate.')
                    result.add_narrative(comment)
                    result.add_recommendation(
                        Recommendation(
                            key='HCC003v1_RECOMMEND_DIAGNOSE_RENAL_DISEASE',
                            rank=3,
                            button='Diagnose',
                            title=title,
                            narrative=comment,
                            command={'key': 'diagnose'}))

                if self.has_suspect_circulatory_condition:
                    comment = (
                        '{0} has Diabetes without complications AND '
                        'a circulatory condition commonly caused by diabetes on the Conditions list.'  # noqa: E501
                    ).format(self.patient.first_name)
                    title = (
                        'Consider updating the Diabetes without complications (E11.9) '
                        'to Diabetes with secondary circulatory disorder as clinically appropriate.'  # noqa: E501
                    )
                    result.add_narrative(comment)
                    result.add_recommendation(
                        Recommendation(
                            key='HCC003v1_RECOMMEND_DIAGNOSE_CIRCULATORY_DISORDER',
                            rank=4,
                            button='Diagnose',
                            title=title,
                            narrative=comment,
                            command={'key': 'diagnose'}))

                if self.has_suspect_other_condition:
                    comment = (
                        '{0} has Diabetes without complications AND '
                        'an another condition commonly caused by diabetes on the Conditions list.'
                    ).format(self.patient.first_name)
                    title = (
                        'Consider updating the Diabetes without complications (E11.9) '
                        'to Diabetes with other secondary complication as clinically appropriate.')
                    result.add_narrative(comment)
                    result.add_recommendation(
                        Recommendation(
                            key='HCC003v1_RECOMMEND_DIAGNOSE_COMPLICATION',
                            rank=5,
                            button='Diagnose',
                            title=title,
                            narrative=comment,
                            command={'key': 'diagnose'}))

            else:
                result.status = STATUS_SATISFIED
        return result
