import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2018 import Trauma
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesIndividualCounseling
from canvas_workflow_kit.value_set.v2021.encounter import BehavioralHealthFollowUpVisit
from canvas_workflow_kit.value_set.v2021.encounter_performed import HospitalInpatientVisitInitial
from canvas_workflow_kit.recommendation import InstructionRecommendation, FollowUpRecommendation, PlanRecommendation

class ConcussionValueSet(ValueSet): pass
class NeuroConditionValueSet(ValueSet): pass
class CervicalSpineInjuryValueSet(ValueSet): pass

class RTPProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        concussion_events = self.patient.conditions.find(ConcussionValueSet)
        return len(concussion_events) > 0

    def in_denominator(self) -> bool:
        concussion_events = self.patient.conditions.find(ConcussionValueSet)
        tbi_events = self.patient.conditions.find(Trauma)
        neuro_conditions = self.patient.conditions.find(NeuroConditionValueSet)
        cervical_spine_injuries = self.patient.conditions.find(CervicalSpineInjuryValueSet)
        return (
            len(concussion_events) > 0 and
            len(tbi_events) == 0 and
            len(neuro_conditions) == 0 and
            len(cervical_spine_injuries) == 0
        )

    def in_numerator(self) -> bool:
        return_to_play = self.patient.conditions.find(ConcussionValueSet)
        return len(return_to_play) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE
        result.add_narrative('Return to play protocol for concussion management.')
        if not self.in_numerator():
            result.add_recommendation(InstructionRecommendation(
                key='rest',
                instruction='Advise rest and symptom monitoring.',
                title='Rest and Monitor',
                narrative='Recommend rest and monitoring of symptoms.',
                patient=self.patient
            ))
            result.add_recommendation(FollowUpRecommendation(
                key='follow_up',
                title='Follow-Up Evaluation',
                narrative='Schedule follow-up evaluation to assess recovery.',
                patient=self.patient
            ))
            result.add_recommendation(PlanRecommendation(
                key='return_to_play',
                title='Return to Play Plan',
                narrative='Develop a plan for gradual return to play.',
                patient=self.patient
            ))
        return result