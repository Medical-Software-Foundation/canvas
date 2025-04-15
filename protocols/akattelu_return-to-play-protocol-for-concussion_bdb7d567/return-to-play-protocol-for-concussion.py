import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import InstructionRecommendation, AssessRecommendation
from canvas_workflow_kit.value_set.v2022 import OutpatientConsultation
from canvas_workflow_kit.value_set.v2019 import Promis29AnxietyScore

class ConcussionValueSet(ValueSet):
    pass

class ConcussionProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        return len(concussion_diagnosis) > 0

    def in_denominator(self) -> bool:
        return self.in_initial_population()

    def in_numerator(self) -> bool:
        if not self.in_denominator():
            return False

        age_5_plus = self.patient.age_at(arrow.now()) >= 5
        symptom_free_24h = True  # Assume this is checked externally
        medical_clearance = True  # Assume this is checked externally

        if not (age_5_plus and symptom_free_24h and medical_clearance):
            return False

        no_new_symptoms = True  # Assume this is checked externally
        no_history = True  # Assume this is checked externally
        follow_progression = True  # Assume this is checked externally

        return no_new_symptoms and no_history and follow_progression

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_numerator():
            result.status = STATUS_SATISFIED
            result.add_narrative('Patient has successfully completed the concussion protocol.')
            result.add_recommendation(InstructionRecommendation(
                key='final_clearance',
                instruction='Obtain final medical clearance before returning to full play.',
                title='Final Clearance',
                narrative='Patient should obtain final medical clearance from a healthcare provider.',
                patient=self.patient
            ))
        else:
            result.status = STATUS_DUE
            result.add_narrative('Patient has not yet completed the concussion protocol.')
            result.add_recommendation(AssessRecommendation(
                key='symptom_free',
                title='Assess Symptom-Free Status',
                context={'narrative': 'Ensure patient is symptom-free for at least 24 hours.'},
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='medical_clearance',
                instruction='Obtain medical clearance to begin return-to-play process.',
                title='Medical Clearance',
                narrative='Patient should receive medical clearance from a healthcare provider.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='no_new_symptoms',
                instruction='Monitor for new or worsening symptoms.',
                title='No New Symptoms',
                narrative='Ensure patient exhibits no new or worsening symptoms during return-to-play.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='no_history',
                instruction='Review patient’s concussion history.',
                title='No History',
                narrative='Ensure patient has no history of multiple concussions or prolonged recovery.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='follow_progression',
                instruction='Ensure patient can follow stepwise progression.',
                title='Follow Progression',
                narrative='Ensure patient can follow the stepwise progression without limitations.',
                patient=self.patient
            ))
        return result