import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2020 import MedicationsEncounterCodeSet
from canvas_workflow_kit.value_set.v2021.procedure import FollowUpForBelowNormalBmi
from canvas_workflow_kit.value_set.v2021.encounter import BehavioralHealthFollowUpVisit
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, PlanRecommendation, InstructionRecommendation

class SerotonergicMedications(ValueSet):
    pass

class PotentiatingMedications(ValueSet):
    pass

class SerotoninSyndromeProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        prescribed_meds = self.patient.medications.find(SerotonergicMedications)
        return len(prescribed_meds) > 0

    def in_denominator(self) -> bool:
        two_or_more_meds = self.patient.medications.find(SerotonergicMedications)
        potentiate_combo = self.patient.medications.find(PotentiatingMedications)
        return (len(two_or_more_meds) >= 2) or (len(two_or_more_meds) > 0 and len(potentiate_combo) > 0)

    def in_numerator(self) -> bool:
        history_no_meds = self.patient.conditions.find(SerotonergicMedications).before(arrow.now())
        stable_regimen = self.patient.medications.find(SerotonergicMedications).intersect(arrow.now().shift(months=-6), False)
        palliative_care = self.patient.conditions.find(PotentiatingMedications)
        return (len(history_no_meds) > 0) or (len(stable_regimen) > 0) or (len(palliative_care) > 0)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('No further action needed.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Monitor for serotonin syndrome.')
                diagnose_recommendation = DiagnoseRecommendation(
                    key='serotonin_syndrome_diagnosis',
                    condition=SerotonergicMedications,
                    title='Diagnose Serotonin Syndrome',
                    narrative='Evaluate for serotonin syndrome based on medication history.',
                    patient=self.patient
                )
                plan_recommendation = PlanRecommendation(
                    key='medication_adjustment',
                    title='Adjust Medications',
                    narrative='Consider adjusting serotonergic medications to reduce risk.',
                    patient=self.patient
                )
                instruction_recommendation = InstructionRecommendation(
                    key='patient_education',
                    instruction='Educate patient on symptoms of serotonin syndrome.',
                    title='Provide Patient Education',
                    narrative='Instruct patient to report symptoms of serotonin syndrome.',
                    patient=self.patient
                )
                result.add_recommendation(diagnose_recommendation)
                result.add_recommendation(plan_recommendation)
                result.add_recommendation(instruction_recommendation)
        return result