from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesIndividualCounseling
from canvas_workflow_kit.value_set.v2020 import PhysicalActivityRecommendation
from canvas_workflow_kit.value_set.v2021.procedure import RecommendationToIncreasePhysicalActivity
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.recommendation import ReferRecommendation, AssessRecommendation, DiagnoseRecommendation
import arrow

class ConcussionDiagnosis(ValueSet):
    pass

class ConcussionManagement(ValueSet):
    pass

class ConcussionSymptoms(ValueSet):
    pass

class ReturnToPlayProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return len(self.patient.conditions.find(ConcussionDiagnosis)) > 0

    def in_denominator(self) -> bool:
        diagnosed = len(self.patient.conditions.find(ConcussionDiagnosis)) > 0
        under_care = len(self.patient.procedures.find(ConcussionManagement)) > 0
        completed_rest = len(self.patient.procedures.find(PreventiveCareServicesIndividualCounseling)) > 0
        return diagnosed and under_care and completed_rest

    def in_numerator(self) -> bool:
        not_cleared = len(self.patient.procedures.find(ConcussionManagement)) == 0
        ongoing_symptoms = len(self.patient.conditions.find(ConcussionSymptoms)) > 0
        multiple_concussions = len(self.patient.conditions.find(ConcussionDiagnosis)) > 1
        under_18_no_consent = self.patient.age_at(arrow.now()) < 18
        return not (not_cleared or ongoing_symptoms or multiple_concussions or under_18_no_consent)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE

        if not self.in_numerator():
            result.add_narrative('Patient is not cleared for return-to-play protocol.')
            result.add_recommendation(ReferRecommendation(
                key='clearance',
                referral=ConcussionManagement,
                title='Refer for Clearance',
                narrative='Refer to healthcare professional for clearance to begin return-to-play protocol.',
                patient=self.patient
            ))
            result.add_recommendation(AssessRecommendation(
                key='symptoms',
                condition=ConcussionSymptoms,
                title='Assess Ongoing Symptoms',
                narrative='Evaluate ongoing symptoms of concussion.',
                patient=self.patient
            ))
            result.add_recommendation(DiagnoseRecommendation(
                key='history',
                condition=ConcussionDiagnosis,
                title='Evaluate Concussion History',
                narrative='Assess history of multiple concussions.',
                patient=self.patient
            ))
            result.add_recommendation(ReferRecommendation(
                key='consent',
                referral=PreventiveCareServicesIndividualCounseling,
                title='Obtain Consent',
                narrative='Obtain parental or guardian consent for underage patient.',
                patient=self.patient
            ))

        return result