import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2020 import AnnualWellnessVisit
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit
from canvas_workflow_kit.value_set.v2021.procedure import LaboratoryTestsForHypertension
from canvas_workflow_kit.recommendation import Recommendation, AssessRecommendation, LabRecommendation, InstructionRecommendation, FollowUpRecommendation

class SerotoninMedsValueSet(ValueSet):
    pass

class AdditionalMedsValueSet(ValueSet):
    pass

class SerotoninSyndromeValueSet(ValueSet):
    pass

class ClinicalProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        serotonin_meds = self.patient.medications.find(SerotoninMedsValueSet)
        return len(serotonin_meds) > 0

    def in_denominator(self) -> bool:
        additional_meds = self.patient.medications.find(AdditionalMedsValueSet)
        no_history_ss = len(self.patient.conditions.find(SerotoninSyndromeValueSet)) == 0
        discontinued_meds = len(self.patient.medications.find(SerotoninMedsValueSet)) == 0
        not_palliative_care = len(self.patient.conditions.find(ValueSet)) == 0
        return (len(additional_meds) > 0 and no_history_ss and not discontinued_meds and not_palliative_care)

    def in_numerator(self) -> bool:
        med_review_done = len(self.patient.procedures.find(ValueSet)) > 0
        clinical_assessment_done = len(self.patient.procedures.find(AnnualWellnessVisit | OfficeVisit)) > 0
        lab_tests_done = len(self.patient.lab_reports.find(LaboratoryTestsForHypertension)) > 0
        interactions_addressed = len(self.patient.procedures.find(ValueSet)) > 0
        patients_educated = len(self.patient.interviews.find(ValueSet)) > 0
        follow_up_scheduled = len(self.patient.referral_reports.find(OfficeVisit)) > 0
        return (med_review_done and clinical_assessment_done and lab_tests_done and
                interactions_addressed and patients_educated and follow_up_scheduled)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE
        if not self.in_numerator():
            result.add_narrative('Patient requires further evaluation for serotonin syndrome risk.')
            result.add_recommendation(AssessRecommendation(
                key='med_review',
                title='Conduct Medication Review',
                narrative='Perform a comprehensive medication review to identify potential drug interactions.',
                patient=self.patient
            ))
            result.add_recommendation(AssessRecommendation(
                key='clinical_assessment',
                title='Conduct Clinical Assessment',
                narrative='Perform a clinical assessment for symptoms of serotonin syndrome.',
                patient=self.patient
            ))
            result.add_recommendation(LabRecommendation(
                key='lab_tests',
                lab=LaboratoryTestsForHypertension,
                condition=SerotoninSyndromeValueSet,
                title='Order Laboratory Tests',
                narrative='Order laboratory tests to rule out other causes of symptoms.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='educate_patients',
                instruction=ValueSet,
                title='Educate Patients',
                narrative='Educate patients about the signs and symptoms of serotonin syndrome.',
                patient=self.patient
            ))
            result.add_recommendation(FollowUpRecommendation(
                key='schedule_follow_up',
                title='Schedule Follow-Up',
                narrative='Schedule follow-up appointments to monitor patient’s condition.',
                patient=self.patient
            ))
        return result