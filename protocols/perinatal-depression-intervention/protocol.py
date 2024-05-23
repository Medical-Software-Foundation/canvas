from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.patient import Patient
import arrow
from typing import Type
from typing import List
from canvas_workflow_kit.recommendation import AllergyRecommendation
from canvas_workflow_kit.recommendation import AssessRecommendation
from canvas_workflow_kit.recommendation import DiagnoseRecommendation
from canvas_workflow_kit.recommendation import FollowUpRecommendation
from canvas_workflow_kit.recommendation import ImagingRecommendation
from canvas_workflow_kit.recommendation import ImmunizationRecommendation
from canvas_workflow_kit.recommendation import InstructionRecommendation
from canvas_workflow_kit.recommendation import InterviewRecommendation
from canvas_workflow_kit.recommendation import LabRecommendation
from canvas_workflow_kit.recommendation import PerformRecommendation
from canvas_workflow_kit.recommendation import PlanRecommendation
from canvas_workflow_kit.recommendation import PrescribeRecommendation
from canvas_workflow_kit.recommendation import Recommendation
from canvas_workflow_kit.recommendation import ReferRecommendation
from canvas_workflow_kit.recommendation import StructuredAssessmentRecommendation
from canvas_workflow_kit.recommendation import TaskRecommendation
from canvas_workflow_kit.recommendation import VitalSignRecommendation
from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.protocol import ClinicalQualityMeasure
from canvas_workflow_kit.protocol import STATUS_DUE
from canvas_workflow_kit.protocol import STATUS_SATISFIED
from canvas_workflow_kit.protocol import ProtocolResult
from canvas_workflow_kit.timeframe import Timeframe
class PregnantPersons(ValueSet):
    VALUE_SET_NAME = 'Pregnant Persons'
    SNOMEDCT = {'77386006', '72892002', '237630007', '129125009', '77386006'}
    ICD10CM = {'Z33.1', 'O09.90', 'O09.91', 'O09.92', 'O09.93'}

class PostpartumPersonsAtRiskForDepression(ValueSet):
    VALUE_SET_NAME = 'Persons less than 1 year postpartum at increased risk for depression'
    SNOMEDCT = {'225444004', '408403008', '413767006'}
    ICD10CM = {'Z87.410', 'O90.6', 'F53.0'}

def in_denominator(patient: Patient) -> bool:
    if patient.conditions.find(PregnantPersons).before(arrow.now()):
        return True
    postpartum_end_date = arrow.now().shift(years=-1)
    if patient.conditions.find(PostpartumPersonsAtRiskForDepression).after(postpartum_end_date):
        return True
    return False
class DepressionDiagnosisExclusion(ValueSet):
    VALUE_SET_NAME = 'Depression Diagnosis Exclusion'
    ICD10CM = {'F32.0', 'F32.1', 'F32.2', 'F32.3', 'F32.4', 'F32.5', 'F32.9', 'F33.0', 'F33.1', 'F33.2'}
    ICD9CM = {'296.20', '296.21', '296.22', '296.23', '296.24', '296.25', '296.26', '296.30', '296.31', '296.32'}

def in_numerator(patient: Patient) -> bool:
    current_depression_diagnosis = patient.conditions.find(DepressionDiagnosisExclusion)
    if current_depression_diagnosis:
        return False
    else:
        return True
class ComposerResult:

    def __init__(self, patient: Patient) -> None:
        self.patient = patient
        self.recommendations: List[Recommendation] = []

    def add_task(self, title: str, description: str) -> None:
        key = f'RECOMMEND_TASK_{1 + len(self.recommendations):02d}'
        self.recommendations.append(TaskRecommendation(key=key, title=title, narrative=description, patient=self.patient))

    def add_allergy_assessment(self, title: str, description: str, potential_allergy: Type[ValueSet]) -> None:
        key = f'RECOMMEND_ALLERGY_{1 + len(self.recommendations):02d}'
        self.recommendations.append(AllergyRecommendation(key=key, allergy=potential_allergy, title=title, narrative=description))

    def add_condition_assessment(self, title: str, description: str) -> None:
        key = f'RECOMMEND_ASSESSMENT_{1 + len(self.recommendations):02d}'
        self.recommendations.append(AssessRecommendation(key=key, title=title, context={'narrative': description}, patient=self.patient))

    def add_condition_diagnosis(self, title: str, description: str, condition_to_diagnose: Type[ValueSet]) -> None:
        key = f'RECOMMEND_DIAGNOSIS_{1 + len(self.recommendations):02d}'
        self.recommendations.append(DiagnoseRecommendation(key=key, condition=condition_to_diagnose, title=title, narrative=description, patient=self.patient))

    def add_follow_up_appointment(self, title: str, description: str) -> None:
        key = f'RECOMMEND_FOLLOW_UP_{1 + len(self.recommendations):02d}'
        self.recommendations.append(FollowUpRecommendation(key=key, title=title, narrative=description, patient=self.patient))

    def add_imaging_order(self, title: str, description: str, imaging_to_order: Type[ValueSet]) -> None:
        key = f'RECOMMEND_IMAGING_ORDER_{1 + len(self.recommendations):02d}'
        self.recommendations.append(ImagingRecommendation(key=key, imaging=imaging_to_order, title=title, narrative=description, patient=self.patient))

    def add_immunization_administration(self, title: str, description: str, immunization_to_administer: Type[ValueSet]) -> None:
        key = f'RECOMMEND_IMMUNIZATION_{1 + len(self.recommendations):02d}'
        self.recommendations.append(ImmunizationRecommendation(key=key, immunization=immunization_to_administer, title=title, narrative=description, patient=self.patient))

    def add_instruction(self, title: str, description: str, instruction_to_give: Type[ValueSet]) -> None:
        key = f'RECOMMEND_INSTRUCTION_{1 + len(self.recommendations):02d}'
        self.recommendations.append(InstructionRecommendation(key=key, instruction=instruction_to_give, title=title, narrative=description, patient=self.patient))

    def add_interview(self, title: str, description: str, questionnaire_to_complete: Type[ValueSet]) -> None:
        key = f'RECOMMEND_INTERVIEW_{1 + len(self.recommendations):02d}'
        self.recommendations.append(InterviewRecommendation(key=key, questionnaires=[questionnaire_to_complete], title=title, narrative=description, patient=self.patient))

    def add_lab_order(self, title: str, description: str, laboratory_test_to_order: Type[ValueSet], condition_motivating_test: Type[ValueSet]) -> None:
        key = f'RECOMMEND_LAB_ORDER_{1 + len(self.recommendations):02d}'
        self.recommendations.append(LabRecommendation(key=key, lab=laboratory_test_to_order, title=title, narrative=description, patient=self.patient, condition=condition_motivating_test))

    def add_procedure(self, title: str, description: str, procedure_to_perform: Type[ValueSet], condition_motivating_procedure: Type[ValueSet]) -> None:
        key = f'RECOMMEND_PROCEDURE_{1 + len(self.recommendations):02d}'
        self.recommendations.append(PerformRecommendation(key=key, procedure=procedure_to_perform, condition=condition_motivating_procedure, title=title, narrative=description, patient=self.patient))

    def add_plan_to_create(self, title: str, description: str) -> None:
        key = f'RECOMMEND_PLAN_{1 + len(self.recommendations):02d}'
        self.recommendations.append(PlanRecommendation(key=key, title=title, narrative=description, patient=self.patient))

    def add_prescription(self, title: str, description: str, prescription: Type[ValueSet]) -> None:
        key = f'RECOMMEND_PRESCRIPTION_{1 + len(self.recommendations):02d}'
        self.recommendations.append(PrescribeRecommendation(key=key, prescription=prescription, title=title, narrative=description, patient=self.patient))

    def add_referral(self, title: str, description: str, referral: Type[ValueSet], condition_motivating_referral: Type[ValueSet]) -> None:
        key = f'RECOMMEND_REFERRAL_{1 + len(self.recommendations):02d}'
        self.recommendations.append(ReferRecommendation(key=key, referral=referral, condition=condition_motivating_referral, title=title, narrative=description, patient=self.patient))

    def add_questionnaire(self, title: str, description: str, structured_questionnaire: Type[ValueSet]) -> None:
        key = f'RECOMMEND_QUESTIONNAIRE_{1 + len(self.recommendations):02d}'
        self.recommendations.append(StructuredAssessmentRecommendation(key=key, questionnaires=[structured_questionnaire], title=title, narrative=description, patient=self.patient))

    def add_vital_sign_reading(self, title: str, description: str) -> None:
        key = f'RECOMMEND_VITAL_SIGN_{1 + len(self.recommendations):02d}'
        self.recommendations.append(VitalSignRecommendation(key=key, title=title, narrative=description, patient=self.patient))

class Pregnancy(ValueSet):
    VALUE_SET_NAME = 'Pregnancy'
    SNOMEDCT = {'77386006', '72892002', '289908002', '69449002', '32779002'}
    ICD10CM = {'Z33.1', 'O09.90', 'O80', 'O09.523'}

class PostpartumPeriod(ValueSet):
    VALUE_SET_NAME = 'Postpartum Period'
    SNOMEDCT = {'371664001', '255399007', '237238006'}
    ICD10CM = {'Z39.2', 'O90.6', 'O94'}

class PerinatalDepressionRisk(ValueSet):
    VALUE_SET_NAME = 'Perinatal Depression Risk'
    SNOMEDCT = {'11687002', '192073007', '84757009', '231504000'}
    ICD10CM = {'F53.0', 'O99.340', 'O99.345'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_date = arrow.now()
    one_year_ago = current_date.shift(years=-1)
    is_pregnant = patient.conditions.find(Pregnancy).before(current_date).exists()
    is_postpartum = patient.conditions.find(PostpartumPeriod).after(one_year_ago).exists()
    at_risk_for_perinatal_depression = patient.conditions.find(PerinatalDepressionRisk).exists()
    if (is_pregnant or is_postpartum) and at_risk_for_perinatal_depression:
        result.add_task(title='Screen for Perinatal Depression', description='Screen for perinatal depression using appropriate tools. Consider factors such as personal or family history of depression, additional stressors, and overall mental health status.')
        result.add_follow_up_appointment(title='Schedule Follow-Up for Perinatal Depression Screening', description='Schedule a follow-up appointment to discuss the results of the screening and, if necessary, discuss treatment options.')
    return result

class PerinatalDepressionPrevention(ClinicalQualityMeasure):
    class Meta:
        title = "Perinatal Depression Prevention"
        description = "Recommendations for interventions to prevent perinatal depression in at-risk populations."
        version = "v20240523171414"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240523171414"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.PROCEDURE]

    def in_initial_population(self) -> bool:
        return in_initial_population(self.patient)

    def in_denominator(self) -> bool:
        return self.in_initial_population() and in_denominator(self.patient)

    def in_numerator(self) -> bool:
        return in_numerator(self.patient)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(f"{self.patient.first_name} does not need further attention.")
            else:
                result.status = STATUS_DUE
                result.due_in = -1
                result.add_narrative(f"{self.patient.first_name} does need some attention.")
                for recommendation in recommendations(self.patient).recommendations:
                    result.add_recommendation(recommendation)
        return result
