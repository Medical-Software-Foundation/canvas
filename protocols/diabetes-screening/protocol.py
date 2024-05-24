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
class NonpregnantAdultsAged35to70Years(ValueSet):
    VALUE_SET_NAME = 'Nonpregnant Adults Aged 35 to 70 Years'
    ICD10CM = {'Z71.3', 'Z02.4', 'Z00.00', 'Z00.01'}
    SNOMEDCT = {'160303001', '133931009', '424673000'}

class IndividualsOverweightOrObesity(ValueSet):
    VALUE_SET_NAME = 'Individuals with Overweight or Obesity'
    ICD10CM = {'E66.9', 'E66.01', 'E66.3', 'Z68.35', 'Z68.41'}
    SNOMEDCT = {'238136002', '408512008', '414916001', '162864005', '751000119104'}

def in_denominator(patient: Patient) -> bool:
    current_date = arrow.now()
    age = patient.age_at(current_date)
    if not 35 <= age <= 70:
        return False
    return True
class ExcludedPatientsPregnant(ValueSet):
    VALUE_SET_NAME = 'Pregnant individuals'
    SNOMEDCT = {'77386006', '72892002', '69449002'}
    ICD10CM = {'Z33.1', 'O09.90', 'Z32.1'}

class ExcludedPatientsAge(ValueSet):
    VALUE_SET_NAME = 'Individuals younger than 35 or older than 70 years'
    SNOMEDCT = set()
    ICD10CM = set()

class ExcludedPatientsNormalBMI(ValueSet):
    VALUE_SET_NAME = 'Individuals with a normal weight (BMI < 25)'
    SNOMEDCT = {'248342006', '162864005'}
    ICD10CM = {'Z68.20', 'Z68.24'}

class ExcludedPatientsDiabetesSymptoms(ValueSet):
    VALUE_SET_NAME = 'Individuals with symptoms of diabetes'
    SNOMEDCT = {'422034002', '237599002', '271594007', '267026004', '31321000119101'}
    ICD10CM = {'R73.9', 'E11.9', 'R73.01', 'E10.9'}

def in_numerator(patient: Patient) -> bool:
    if patient.conditions.find(ExcludedPatientsPregnant).exists():
        return False
    current_date = arrow.now()
    age = patient.age_at(current_date)
    if age < 35 or age > 70:
        return False
    bmi = patient.latest_bmi_value()
    if bmi < 25:
        return False
    if patient.conditions.find(ExcludedPatientsDiabetesSymptoms).exists():
        return False
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

class NonpregnantAdultsOverweightObesity(ValueSet):
    VALUE_SET_NAME = 'Nonpregnant adults aged 35 to 70 years who have overweight or obesity and no symptoms of diabetes'
    ICD10CM = {'Z68.35', 'Z68.36', 'Z68.37', 'Z68.38', 'Z68.39', 'Z68.41', 'Z68.42', 'Z68.43', 'Z68.44', 'Z68.45'}

class FastingPlasmaGlucoseTest(ValueSet):
    VALUE_SET_NAME = 'Measurement of fasting plasma glucose'
    LOINC = {'1558-6', '1554-5', '14771-0', '2339-0', '2345-7', '10449-7', '10450-5', '41604-0', '32016-8', '32309-7'}

class HbA1cLevelTest(ValueSet):
    VALUE_SET_NAME = 'Measurement of HbA1c level'
    LOINC = {'4548-4', '4549-2', '17856-6', '59261-8', '62388-4', '71775-9', '71875-7', '7917-8', '17855-8', '59260-0'}

class OralGlucoseToleranceTest(ValueSet):
    VALUE_SET_NAME = 'Oral glucose tolerance test'
    LOINC = {'1558-6', '1554-5', '14771-0', '2339-0', '2345-7', '10449-7', '10450-5', '41604-0', '32016-8', '32309-7'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_year = arrow.now().year
    patient_age = patient.age_at(arrow.now())
    if 35 <= patient_age <= 70 and (not patient.is_female) and (NonpregnantAdultsOverweightObesity in patient.conditions):
        result.add_recommendation(title='Fasting Plasma Glucose Test', description='It is recommended to have a fasting plasma glucose test every 3 years.')
        result.add_recommendation(title='HbA1c Level Test', description='It is recommended to measure HbA1c level every 3 years.')
        result.add_recommendation(title='Oral Glucose Tolerance Test', description='An oral glucose tolerance test is recommended every 3 years.')
    return result

class DiabetesScreeningUSPSTF(ClinicalQualityMeasure):
    class Meta:
        title = "Diabetes Screening Recommendation"
        description = "USPSTF recommends screening for prediabetes and type 2 diabetes in adults aged 35 to 70 with overweight or obesity."
        version = "v20240524042528"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240524042528"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.APPOINTMENT,CHANGE_TYPE.CONDITION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.VITAL_SIGN]

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
