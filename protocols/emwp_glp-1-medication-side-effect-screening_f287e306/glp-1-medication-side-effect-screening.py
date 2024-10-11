import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientPeriodRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2018 import MentalHealthDiagnoses
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesEstablishedOfficeVisit18AndUp, OutpatientConsultation
from canvas_workflow_kit.recommendation import AllergyRecommendation, PrescribeRecommendation, InterviewRecommendation, ReferRecommendation

class GLP1Medications(ValueSet):
    pass

class GLP1Allergies(ValueSet):
    pass

class GLP1SideEffects(ValueSet):
    pass

class GLP1ClinicalTrial(ValueSet):
    pass

class GLP1Protocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1Medications)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_4_weeks_ago = arrow.now().shift(weeks=-4)
        end_3_months_ago = arrow.now().shift(months=-3)
        glp1_duration = self.patient.prescriptions.find(GLP1Medications).intersects(start_4_weeks_ago, True)
        recent_screening = self.patient.interviews.find(GLP1SideEffects).after(end_3_months_ago)
        return len(glp1_duration) > 0 and len(recent_screening) == 0

    def in_numerator(self) -> bool:
        no_allergies = len(self.patient.allergy_intolerances.find(GLP1Allergies)) == 0
        not_discontinued = len(self.patient.medications.find(GLP1Medications).stopped_after(arrow.now().shift(weeks=-4))) == 0
        not_in_trial = len(self.patient.procedures.find(GLP1ClinicalTrial).after(arrow.now().shift(months=-6))) == 0
        not_terminal = len(self.patient.conditions.find(MentalHealthDiagnoses)) == 0
        return no_allergies and not_discontinued and not_in_trial and not_terminal

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE
        if not self.in_numerator():
            result.add_narrative('Patient is eligible for GLP-1 side effect screening.')
            result.add_recommendation(AllergyRecommendation(
                key='glp1_allergy_check',
                title='Check for GLP-1 Allergies',
                allergy=GLP1Allergies,
                narrative='Verify no documented allergies to GLP-1 medications.'
            ))
            result.add_recommendation(PrescribeRecommendation(
                key='glp1_prescription',
                title='Continue GLP-1 Prescription',
                prescription=GLP1Medications,
                narrative='Ensure GLP-1 medication is not discontinued.'
            ))
            result.add_recommendation(InterviewRecommendation(
                key='glp1_side_effects',
                title='Conduct GLP-1 Side Effects Interview',
                interview=GLP1SideEffects,
                narrative='Administer questionnaire to assess GLP-1 side effects.'
            ))
            result.add_recommendation(ReferRecommendation(
                key='clinical_trial_check',
                title='Check Clinical Trial Participation',
                referral=GLP1ClinicalTrial,
                narrative='Ensure patient is not in a GLP-1 clinical trial.'
            ))
            result.add_recommendation(ReferRecommendation(
                key='terminal_illness_check',
                title='Check for Terminal Illness',
                referral=MentalHealthDiagnoses,
                narrative='Verify patient does not have a terminal illness.'
            ))
        return result