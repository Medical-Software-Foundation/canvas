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
class Adults40YearsOrOlderWithoutCVD(ValueSet):
    VALUE_SET_NAME = 'Adults 40 years or older without signs or symptoms of CVD or known CVD'
    SNOMEDCT = {'160267008', '133931009', '426788004', '275918005', '2667000', '416098002', '429457001', '426249004', '161891005', '105539002'}

class Adults40To59YearsWith10PercentCVD(ValueSet):
    VALUE_SET_NAME = 'Adults aged 40 to 59 years with a 10% or greater 10-year CVD risk'
    SNOMEDCT = {'160267008', '133931009', '428875002', '713422000', '394701000', '105539002', '38341003', '441829007', '69896004', '413350009'}

def in_denominator(patient: Patient) -> bool:
    current_date = arrow.now()
    age = patient.age_at(current_date)
    if age >= 40:
        return True
    if 40 <= age <= 59:
        return True
    return False
class ExcludedPatients1(ValueSet):
    VALUE_SET_NAME = 'Excluded Patients 1 - Conditions increasing bleeding risk'
    ICD10CM = {'K25', 'K26', 'K27', 'K28', 'R58', 'D68.9', 'I85.00', 'I98.3'}
    SNOMEDCT = {'3545003', '449868002', '128477000', '42343007'}

class ExcludedPatients2(ValueSet):
    VALUE_SET_NAME = 'Excluded Patients 2 - Age 60+ with no net benefit from low-dose aspirin'

def in_numerator(patient: Patient) -> bool:
    if patient.conditions.find(ExcludedPatients1).exists() or patient.medications.find(ExcludedPatients1).exists():
        return False
    current_date = arrow.now()
    age = patient.age_at(current_date)
    if age >= 60:
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

class LowDoseAspirinUse(ValueSet):
    VALUE_SET_NAME = 'Low-dose Aspirin Use for Adults 40 to 59 Years with CVD Risk'
    RXNORM = {'243670', '243671', '314231', '849574', '617312', '200345', '1115008', '313002', '197361', '849855'}
    SNOMEDCT = {'386373004', '428041000124106', '428061000124105', '325072002', '763158003', '372763004', '225151006', '225152004', '225153009', '225154003'}

class LowDoseAspirinNotRecommended(ValueSet):
    VALUE_SET_NAME = 'Low-dose Aspirin Use Not Recommended for Adults 60 Years or Older'
    SNOMEDCT = {'410534003', '428071000124103', '428081000124100', '416098002', '416406003', '445528004', '702321005', '710081004', '225150007', '182890002'}
    RXNORM = {'243670', '243671', '314231', '849574', '617312', '200345', '1115008', '313002', '197361', '849855'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_age = patient.age_at(arrow.now())
    if 40 <= current_age < 60:
        cvd_risk = True
        not_at_risk_for_bleeding = True
        if cvd_risk and not_at_risk_for_bleeding:
            result.add_recommendation(title='Consider Low-Dose Aspirin', description='Patient is aged 40 to 59 years with a 10% or greater 10-year CVD risk and is not at increased risk for bleeding. Consider daily low-dose aspirin use.')
    if current_age >= 60:
        result.add_recommendation(title='Low-Dose Aspirin Not Recommended', description='For adults 60 years or older, the USPSTF recommends against initiating low-dose aspirin use for the primary prevention of CVD.')
    return result

class AspirinCVDPreventionUSPSTF(ClinicalQualityMeasure):
    class Meta:
        title = "Aspirin and CVD Prevention"
        description = "USPSTF recommendations on aspirin use to prevent cardiovascular disease"
        version = "v20240606032608"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240606032608"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.ALLERGY_INTOLERANCE,CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.PRESCRIPTION,CHANGE_TYPE.VITAL_SIGN]

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
