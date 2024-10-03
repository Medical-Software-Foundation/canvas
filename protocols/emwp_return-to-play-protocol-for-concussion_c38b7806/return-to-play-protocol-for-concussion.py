import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import BipolarDiagnosis
from canvas_workflow_kit.value_set.v2021.encounter_performed import MedicalDisabilityExam, OfficeVisit
from canvas_workflow_kit.value_set.v2021.assessment import StandardizedPainAssessmentTool
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import PlanRecommendation, DiagnoseRecommendation, PerformRecommendation, InstructionRecommendation, ClearanceRecommendation

class ReturnToPlayProtocol(ClinicalQualityMeasure):
    class Meta:
        title = 'Return to Play Protocol'

    def in_initial_population(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(BipolarDiagnosis)
        return len(concussion_diagnosis) > 0

    def in_denominator(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(BipolarDiagnosis)
        post_acute_time = arrow.now().shift(days=-1)
        initial_evaluation = self.patient.procedures.find(OfficeVisit)
        return (len(concussion_diagnosis) > 0 and
                len(initial_evaluation) > 0)

    def in_numerator(self) -> bool:
        severe_symptoms = self.patient.conditions.find(BipolarDiagnosis)
        multiple_concussions = self.patient.conditions.find(BipolarDiagnosis)
        coexisting_conditions = self.patient.conditions.find(BipolarDiagnosis)
        no_clearance = self.patient.conditions.find(MedicalDisabilityExam)
        cognitive_test = self.patient.procedures.find(StandardizedPainAssessmentTool)
        balance_test = self.patient.procedures.find(StandardizedPainAssessmentTool)
        no_symptoms = self.patient.conditions.find(BipolarDiagnosis)
        medical_clearance = self.patient.procedures.find(MedicalDisabilityExam)
        return (len(severe_symptoms) == 0 and
                len(multiple_concussions) == 0 and
                len(coexisting_conditions) == 0 and
                len(no_clearance) == 0 and
                len(cognitive_test) > 0 and
                len(balance_test) > 0 and
                len(no_symptoms) == 0 and
                len(medical_clearance) > 0)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has successfully completed the return-to-play protocol.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient needs to complete the return-to-play protocol.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='severe_symptoms',
                    condition=BipolarDiagnosis,
                    title='Evaluate Severe Symptoms',
                    narrative='Assess and manage any severe or worsening neurological symptoms.',
                    patient=self.patient
                ))
                result.add_recommendation(DiagnoseRecommendation(
                    key='multiple_concussions',
                    condition=BipolarDiagnosis,
                    title='Evaluate Multiple Concussions',
                    narrative='Assess history of multiple concussions and prolonged recovery.',
                    patient=self.patient
                ))
                result.add_recommendation(DiagnoseRecommendation(
                    key='coexisting_conditions',
                    condition=BipolarDiagnosis,
                    title='Evaluate Coexisting Conditions',
                    narrative='Assess any co-existing medical conditions that may complicate recovery.',
                    patient=self.patient
                ))
                result.add_recommendation(ClearanceRecommendation(
                    key='no_clearance',
                    condition=MedicalDisabilityExam,
                    title='Obtain Medical Clearance',
                    narrative='Ensure medical clearance is obtained to proceed with the protocol.',
                    patient=self.patient
                ))
                result.add_recommendation(PerformRecommendation(
                    key='cognitive_test',
                    procedure=StandardizedPainAssessmentTool,
                    title='Perform Cognitive Test',
                    narrative='Conduct neurocognitive testing to assess baseline cognitive function.',
                    patient=self.patient
                ))
                result.add_recommendation(PerformRecommendation(
                    key='balance_test',
                    procedure=StandardizedPainAssessmentTool,
                    title='Perform Balance Test',
                    narrative='Conduct balance and coordination tests to assess recovery.',
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='no_symptoms',
                    instruction='Monitor Symptoms',
                    title='Monitor Symptoms',
                    narrative='Instruct patient to report any persistent or new symptoms.',
                    patient=self.patient
                ))
                result.add_recommendation(ClearanceRecommendation(
                    key='medical_clearance',
                    condition=MedicalDisabilityExam,
                    title='Obtain Final Clearance',
                    narrative='Ensure final medical clearance is obtained to complete the protocol.',
                    patient=self.patient
                ))
        return result