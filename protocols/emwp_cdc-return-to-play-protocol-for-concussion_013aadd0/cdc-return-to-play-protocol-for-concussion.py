from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2020 import AboveNormalFollowUp
from canvas_workflow_kit.value_set.v2021.procedure import FollowUpForAboveNormalBmi
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.value_set.v2020 import HealthAndBehavioralAssessmentInitial
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import AssessRecommendation, InstructionRecommendation, PlanRecommendation
import arrow

class ConcussionValueSet(ValueSet):
    pass

class NeurologicalConditionsValueSet(ValueSet):
    pass

class ReturnToPlayProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        return len(concussion_diagnosis) > 0

    def in_denominator(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        pre_existing_conditions = self.patient.conditions.find(NeurologicalConditionsValueSet)
        return (
            len(concussion_diagnosis) > 0 and
            len(pre_existing_conditions) == 0
        )

    def in_numerator(self) -> bool:
        return (
            self.in_denominator() and
            len(self.patient.procedures.find(HealthAndBehavioralAssessmentInitial)) > 0
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has completed the return-to-play protocol.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient needs to complete the return-to-play protocol.')
                result.add_recommendation(AssessRecommendation(
                    key='neurocognitive_testing',
                    title='Conduct Neurocognitive Testing',
                    context={'procedures': ['Neurocognitive Testing']},
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='symptom_assessment',
                    instruction='Conduct symptom assessment using standardized checklists.',
                    patient=self.patient
                ))
                result.add_recommendation(PlanRecommendation(
                    key='graduated_protocol',
                    title='Implement Graduated Return-to-Play Protocol',
                    context={'instructions': ['Complete a stepwise increase in physical activity.']},
                    patient=self.patient
                ))
        return result