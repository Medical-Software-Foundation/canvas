import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2022 import MedicationsForAboveNormalBmi
from canvas_workflow_kit.recommendation import PrescribeRecommendation, AllergyRecommendation, InstructionRecommendation

class GLP1Measure(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Medication Monitoring'

    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(MedicationsForAboveNormalBmi)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_date = arrow.now().shift(weeks=-4)
        glp1_medications = self.patient.medications.find(MedicationsForAboveNormalBmi)
        return len(glp1_medications) > 0 and glp1_medications.start_date < start_date

    def in_numerator(self) -> bool:
        glp1_allergies = self.patient.allergy_intolerances.find(MedicationsForAboveNormalBmi)
        return len(glp1_allergies) == 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient is compliant with GLP-1 medication protocol.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient has not met all GLP-1 medication protocol criteria.')
                prescribe_recommendation = PrescribeRecommendation(
                    key='continue_glp1',
                    prescription=MedicationsForAboveNormalBmi,
                    title='Continue GLP-1 Medication',
                    narrative='Recommend continuing GLP-1 medication as no allergies are present.',
                    patient=self.patient
                )
                allergy_recommendation = AllergyRecommendation(
                    key='check_allergies',
                    title='Check GLP-1 Allergies',
                    narrative='Verify no allergies to GLP-1 medications.',
                    patient=self.patient
                )
                instruction_recommendation = InstructionRecommendation(
                    key='trial_instruction',
                    instruction='Avoid Clinical Trials',
                    title='Avoid Clinical Trials',
                    narrative='Advise patient to avoid clinical trials involving GLP-1 medications.',
                    patient=self.patient
                )
                result.add_recommendation(prescribe_recommendation)
                result.add_recommendation(allergy_recommendation)
                result.add_recommendation(instruction_recommendation)
        return result