import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, ReferRecommendation
from canvas_workflow_kit.value_set.v2021.medication import PharmacologicTherapyForHypertension, Amoxapine
from canvas_workflow_kit.value_set.v2021.diagnosis import HeartFailure

class HeartFailureProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        hf_medications = self.patient.medications.find(PharmacologicTherapyForHypertension | Amoxapine)
        return len(hf_medications) > 0

    def in_denominator(self) -> bool:
        hf_diagnosis = self.patient.conditions.find(HeartFailure)
        return len(hf_diagnosis) == 0

    def in_numerator(self) -> bool:
        hf_diagnosis = self.patient.conditions.find(HeartFailure)
        return len(hf_diagnosis) == 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
            return result

        result.status = STATUS_SATISFIED
        result.add_narrative('Patient is in the subset for consideration.')

        if not self.in_numerator():
            result.status = STATUS_DUE
            result.add_narrative('Review patient’s heart failure medication use.')

            diagnose_recommendation = DiagnoseRecommendation(
                key='hf_diagnosis',
                condition=HeartFailure,
                title='Evaluate Heart Failure Medication',
                narrative='Consider evaluating the need for heart failure medication.',
                patient=self.patient
            )
            result.add_recommendation(diagnose_recommendation)

            diagnose_pending = DiagnoseRecommendation(
                key='pending_hf_diagnosis',
                condition=HeartFailure,
                title='Pending Heart Failure Evaluation',
                narrative='Patient has a pending heart failure evaluation.',
                patient=self.patient
            )
            result.add_recommendation(diagnose_pending)

            refer_recommendation = ReferRecommendation(
                key='trial_participation',
                referral=HeartFailure,
                title='Clinical Trial Participation',
                narrative='Patient is participating in a clinical trial for heart failure medication.',
                patient=self.patient
            )
            result.add_recommendation(refer_recommendation)

        return result