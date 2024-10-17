import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2018 import MentalHealthDiagnoses
from canvas_workflow_kit.value_set.v2021.encounter_performed import OutpatientConsultation
from canvas_workflow_kit.recommendation import AssessRecommendation, InstructionRecommendation, InterviewRecommendation, LabRecommendation

class GLP1MedicationValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1SideEffectScreeningProtocol(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Side Effect Screening'

    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1MedicationValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_4_weeks_ago = arrow.now().shift(weeks=-4)
        end_3_months_ago = arrow.now().shift(months=-3)
        glp1_duration = self.patient.prescriptions.find(GLP1MedicationValueSet).intersects(start_4_weeks_ago, True)
        recent_screening = self.patient.interviews.find(GLP1AllergyValueSet).after(end_3_months_ago)
        return len(glp1_duration) > 0 and len(recent_screening) == 0

    def in_numerator(self) -> bool:
        no_allergies = len(self.patient.allergy_intolerances.find(GLP1AllergyValueSet)) == 0
        not_discontinued = len(self.patient.medications.find(GLP1MedicationValueSet).intersects(arrow.now().shift(weeks=-4), True)) > 0
        not_in_trial = True  # Assume no trial participation data available
        not_terminal = len(self.patient.conditions.find(MentalHealthDiagnoses)) == 0
        return no_allergies and not_discontinued and not_in_trial and not_terminal

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('GLP-1 side effect screening is up to date.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('GLP-1 side effect screening is needed.')
                result.add_recommendation(InstructionRecommendation(
                    key='discontinue',
                    instruction='Consider discontinuing GLP-1 medication if side effects are identified.',
                    title='Discontinue GLP-1',
                    narrative='Recommend discontinuing GLP-1 medication if side effects are identified.'
                ))
                result.add_recommendation(InterviewRecommendation(
                    key='side_effects',
                    interview='GLP-1 Side Effects Questionnaire',
                    title='Conduct Side Effects Interview',
                    narrative='Conduct an interview to assess GLP-1 side effects.',
                    patient=self.patient
                ))
                result.add_recommendation(LabRecommendation(
                    key='labs',
                    lab='GLP-1 Side Effects Panel',
                    title='Order Labs',
                    narrative='Order labs to evaluate GLP-1 side effects.',
                    patient=self.patient
                ))
                result.add_recommendation(AssessRecommendation(
                    key='consultation',
                    title='Consultation',
                    context={'narrative': 'Recommend a consultation to address GLP-1 side effects.'},
                    patient=self.patient
                ))
        return result