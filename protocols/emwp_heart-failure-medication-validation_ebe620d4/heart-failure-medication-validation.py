import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, StopRecommendation
from canvas_workflow_kit.value_set.v2021.diagnosis import HeartFailure
from canvas_workflow_kit.value_set.v2021.medication import PharmacologicTherapyForHypertension, Amoxapine

class ClinicalTrialParticipationValueSet(ValueSet):
    pass

class HeartFailureMedicationProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        active_medications = self.patient.medications.find(PharmacologicTherapyForHypertension | Amoxapine)
        return len(active_medications) > 0

    def in_denominator(self) -> bool:
        hf_diagnosis = self.patient.conditions.find(HeartFailure)
        return len(hf_diagnosis) == 0

    def in_numerator(self) -> bool:
        hf_history = self.patient.conditions.find(HeartFailure).before(arrow.now())
        off_label_justification = self.patient.procedures.find(PharmacologicTherapyForHypertension | Amoxapine)
        clinical_trial = self.patient.procedures.find(ClinicalTrialParticipationValueSet)
        return len(hf_history) > 0 or len(off_label_justification) > 0 or len(clinical_trial) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_numerator():
            result.status = STATUS_SATISFIED
            result.add_narrative('Heart failure medication is justified.')
        else:
            result.status = STATUS_DUE
            result.add_narrative('Review heart failure medication use.')
            diagnose_recommendation = DiagnoseRecommendation(
                key='diagnose_hf',
                condition=HeartFailure,
                title='Diagnose Heart Failure',
                narrative='Recommend diagnosing heart failure based on diagnostic tests.',
                patient=self.patient
            )
            stop_recommendation = StopRecommendation(
                key='stop_medication',
                title='Stop Heart Failure Medication',
                narrative='Recommend stopping heart failure medication due to lack of justification.',
                patient=self.patient
            )
            result.add_recommendation(diagnose_recommendation)
            result.add_recommendation(stop_recommendation)
        return result