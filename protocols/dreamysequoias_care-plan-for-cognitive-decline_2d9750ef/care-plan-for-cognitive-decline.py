import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import Recommendation, InstructionRecommendation, PlanRecommendation, StructuredAssessmentRecommendation
from canvas_workflow_kit.value_set.v2022 import CognitiveAssessment, StandardizedToolsForAssessmentOfCognition, Phq9AndPhq9MTools, FollowUpWithin4Weeks

class CognitiveCarePlanValueSet(ValueSet):
    pass

class CognitiveDeclineProtocol(ClinicalQualityMeasure):
    class Meta:
        title = 'Cognitive Decline Management'

    def in_initial_population(self) -> bool:
        structured_assessments = self.patient.interviews.find(StandardizedToolsForAssessmentOfCognition)
        questionnaires = self.patient.interviews.find(Phq9AndPhq9MTools)
        return len(structured_assessments) > 0 and len(questionnaires) > 0

    def in_denominator(self) -> bool:
        modifiable_risk_factors = self.patient.interviews.find(StandardizedToolsForAssessmentOfCognition).after(arrow.now().shift(years=-1))
        return len(modifiable_risk_factors) > 0

    def in_numerator(self) -> bool:
        conflicting_care_plan = self.patient.careplans.find(FollowUpWithin4Weeks)
        return len(conflicting_care_plan) == 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Cognitive care plan is in place and no conflicts found.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient has modifiable risk factors for cognitive decline.')
                result.add_narrative('No conflicting care plan found.')
                admin_recommendation = InstructionRecommendation(
                    key='admin_action',
                    instruction='Implement a user interface feature: a button at the patient level in the top menu of the EHR system.',
                    title='Administrative Action',
                    narrative='Implement a user interface feature for cognitive care management.',
                    patient=self.patient
                )
                data_processing_recommendation = StructuredAssessmentRecommendation(
                    key='data_processing',
                    questionnaires=[StandardizedToolsForAssessmentOfCognition, Phq9AndPhq9MTools],
                    title='Data Processing',
                    narrative='Process the structured assessment and questionnaire responses.',
                    patient=self.patient
                )
                document_generation_recommendation = InstructionRecommendation(
                    key='document_generation',
                    instruction='Generate a new external document in RTF format.',
                    title='Document Generation',
                    narrative='Generate a new RTF document for cognitive care plan.',
                    patient=self.patient
                )
                care_plan_recommendation = PlanRecommendation(
                    key='care_plan_development',
                    plan=FollowUpWithin4Weeks,
                    title='Care Plan Development',
                    narrative='Develop a comprehensive care plan for cognitive decline management.',
                    patient=self.patient
                )
                review_recommendation = InstructionRecommendation(
                    key='review_approval',
                    instruction='Ensure the care plan is reviewed by a healthcare professional.',
                    title='Review and Approval',
                    narrative='Review the care plan for accuracy and relevance.',
                    patient=self.patient
                )
                result.add_recommendation(admin_recommendation)
                result.add_recommendation(data_processing_recommendation)
                result.add_recommendation(document_generation_recommendation)
                result.add_recommendation(care_plan_recommendation)
                result.add_recommendation(review_recommendation)
        return result