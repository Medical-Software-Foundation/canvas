import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.medication import PharmacologicTherapyForHypertension
from canvas_workflow_kit.value_set.v2021.diagnosis import HeartFailure
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.value_set.v2020 import ContactOrOfficeVisit
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, PrescribeRecommendation, ReferRecommendation

class HeartFailureProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return len(self.patient.medications.find(PharmacologicTherapyForHypertension)) > 0

    def in_denominator(self) -> bool:
        hf_diagnosis = self.patient.conditions.find(HeartFailure)
        return len(hf_diagnosis) == 0

    def in_numerator(self) -> bool:
        inactive_hf = self.patient.conditions.find(HeartFailure).before(arrow.now())
        off_label_use = self.patient.medications.find(PharmacologicTherapyForHypertension).before(arrow.now())
        clinical_trial = self.patient.procedures.find(OfficeVisit).before(arrow.now())
        return len(inactive_hf) > 0 or len(off_label_use) > 0 or len(clinical_trial) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Heart failure management is appropriate.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Review heart failure management.')
                diagnose_recommendation = DiagnoseRecommendation(
                    key='hf_diagnosis',
                    condition=HeartFailure,
                    title='Diagnose Heart Failure',
                    narrative='Evaluate for active heart failure diagnosis.',
                    patient=self.patient
                )
                prescribe_recommendation = PrescribeRecommendation(
                    key='hf_medication',
                    prescription=PharmacologicTherapyForHypertension,
                    title='Prescribe Heart Failure Medication',
                    narrative='Continue or adjust heart failure medication.',
                    patient=self.patient
                )
                refer_recommendation = ReferRecommendation(
                    key='clinical_trial',
                    referral=OfficeVisit,
                    title='Refer to Clinical Trial',
                    narrative='Consider referral to heart failure clinical trial.',
                    patient=self.patient
                )
                result.add_recommendation(diagnose_recommendation)
                result.add_recommendation(prescribe_recommendation)
                result.add_recommendation(refer_recommendation)
        return result