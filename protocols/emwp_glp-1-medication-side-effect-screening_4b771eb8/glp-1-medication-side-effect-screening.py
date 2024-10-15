import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2018 import MentalHealthDiagnoses
from canvas_workflow_kit.value_set.v2021.encounter_performed import OutpatientConsultation
from canvas_workflow_kit.recommendation import AllergyRecommendation, InstructionRecommendation, DiagnoseRecommendation

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1TrialValueSet(ValueSet):
    pass

class GLP1Protocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_4_weeks_ago = arrow.now().shift(weeks=-4)
        end_3_months_ago = arrow.now().shift(months=-3)
        glp1_duration = self.patient.prescriptions.find(GLP1ValueSet).before(start_4_weeks_ago)
        recent_screening = self.patient.interviews.find(GLP1ValueSet).after(end_3_months_ago)
        return len(glp1_duration) > 0 and len(recent_screening) == 0

    def in_numerator(self) -> bool:
        no_allergies = len(self.patient.allergy_intolerances.find(GLP1AllergyValueSet)) == 0
        not_discontinued = len(self.patient.medications.find(GLP1ValueSet).before(arrow.now().shift(weeks=-4))) == 0
        not_in_trial = len(self.patient.procedures.find(GLP1TrialValueSet)) == 0
        not_terminal = len(self.patient.conditions.find(MentalHealthDiagnoses)) == 0
        return no_allergies and not_discontinued and not_in_trial and not_terminal

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient is eligible for GLP-1 side effect screening.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient requires GLP-1 side effect screening.')
                result.add_recommendation(AllergyRecommendation(
                    key='glp1_allergy',
                    title='Check GLP-1 Allergies',
                    allergy=GLP1AllergyValueSet,
                    narrative='Verify and document any allergies to GLP-1 medications.'
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='discontinuation',
                    title='Review GLP-1 Discontinuation',
                    instructions='Ensure GLP-1 medications have not been discontinued in the last 4 weeks.',
                    narrative='Check for recent discontinuation of GLP-1 medications.'
                ))
                result.add_recommendation(DiagnoseRecommendation(
                    key='trial_participation',
                    title='Assess Clinical Trial Participation',
                    condition=GLP1TrialValueSet,
                    narrative='Evaluate if the patient is participating in a GLP-1 clinical trial.'
                ))
                result.add_recommendation(DiagnoseRecommendation(
                    key='terminal_illness',
                    title='Evaluate Terminal Illness',
                    condition=MentalHealthDiagnoses,
                    narrative='Assess for terminal illness impacting medication management.'
                ))
        return result