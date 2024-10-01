import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import HeartFailure
from canvas_workflow_kit.value_set.v2020 import Outpatient
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, PrescribeRecommendation, PlanRecommendation

class HeartFailureMedicationValueSet(ValueSet):
    pass

class HeartFailureMedicationProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return len(self.patient.medications.find(HeartFailureMedicationValueSet)) > 0

    def in_denominator(self) -> bool:
        no_active_diagnosis = len(self.patient.conditions.find(HeartFailure)) == 0
        return self.in_initial_population() and no_active_diagnosis

    def in_numerator(self) -> bool:
        history_inactive = len(self.patient.conditions.find(HeartFailure)) > 0
        off_label_use = len(self.patient.procedures.find(HeartFailureMedicationValueSet)) > 0
        clinical_trial = len(self.patient.referral_reports.find(HeartFailureMedicationValueSet)) > 0
        return history_inactive or off_label_use or clinical_trial

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Heart failure medication is justified.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='heart_failure_diagnosis',
                    condition=HeartFailure,
                    title='Confirm Heart Failure Diagnosis',
                    narrative='Confirm the diagnosis of heart failure based on clinical assessment and diagnostic tests.',
                    patient=self.patient
                ))
                result.add_recommendation(PrescribeRecommendation(
                    key='off_label_prescription',
                    prescription=HeartFailureMedicationValueSet,
                    title='Continue Off-Label Prescription',
                    narrative='Continue heart failure medication for off-label use with documented justification.',
                    patient=self.patient
                ))
                result.add_recommendation(PlanRecommendation(
                    key='clinical_trial_plan',
                    title='Continue Clinical Trial',
                    narrative='Continue participation in the clinical trial involving heart failure medication.',
                    patient=self.patient
                ))
            else:
                result.status = STATUS_DUE
                result.add_narrative('Re-evaluate the need for heart failure medication.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='discontinue_diagnosis',
                    condition=HeartFailure,
                    title='Discontinue Heart Failure Medication',
                    narrative='Discontinue or adjust heart failure medication due to inactive diagnosis.',
                    patient=self.patient
                ))
        return result