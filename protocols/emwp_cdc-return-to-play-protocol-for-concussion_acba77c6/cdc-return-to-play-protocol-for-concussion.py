import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2020 import AboveNormalFollowUp, PhysicalActivityRecommendation
from canvas_workflow_kit.value_set.v2021.procedure import FollowUpForAboveNormalBmi, RecommendationToIncreasePhysicalActivity
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.value_set.v2021.encounter import EncounterToEvaluateBmi
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import AssessRecommendation, InstructionRecommendation, PlanRecommendation, TaskRecommendation

class ConcussionDiagnosis(ValueSet):
    pass

class NeurologicalConditions(ValueSet):
    pass

class SportsConcussion(ValueSet):
    pass

class ReturnToPlayProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return len(self.patient.procedures.find(SportsConcussion)) > 0 and len(self.patient.conditions.find(ConcussionDiagnosis)) > 0

    def in_denominator(self) -> bool:
        return self.in_initial_population() and len(self.patient.conditions.find(ConcussionDiagnosis)) > 0 and len(self.patient.conditions.find(NeurologicalConditions)) == 0

    def in_numerator(self) -> bool:
        return self.in_denominator() and len(self.patient.procedures.find(SportsConcussion)) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has completed the return-to-play protocol successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient needs to complete the return-to-play protocol.')
                result.add_recommendation(AssessRecommendation(
                    key='initial_eval',
                    title='Initial Medical Evaluation',
                    context={'condition': 'concussion'},
                    patient=self.patient
                ))
                result.add_recommendation(TaskRecommendation(
                    key='neurocog_test',
                    title='Neurocognitive Testing',
                    context={'condition': 'concussion'},
                    patient=self.patient
                ))
                result.add_recommendation(AssessRecommendation(
                    key='symptom_assess',
                    title='Symptom Assessment',
                    context={'condition': 'concussion'},
                    patient=self.patient
                ))
                result.add_recommendation(TaskRecommendation(
                    key='balance_test',
                    title='Balance and Coordination Testing',
                    context={'condition': 'concussion'},
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='symptom_free',
                    instruction='Ensure patient is symptom-free at rest and during exertion.',
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='baseline_return',
                    instruction='Ensure return to baseline neurocognitive function.',
                    patient=self.patient
                ))
                result.add_recommendation(PlanRecommendation(
                    key='grad_return',
                    title='Graduated Return-to-Play Protocol',
                    context={'condition': 'concussion'},
                    patient=self.patient
                ))
                result.add_recommendation(AssessRecommendation(
                    key='final_clearance',
                    title='Final Clearance',
                    context={'condition': 'concussion'},
                    patient=self.patient
                ))
        return result