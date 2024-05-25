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
class Adults18YearsOrOlderIncludingPregnantAndPostpartumWomen(ValueSet):
    VALUE_SET_NAME = 'Adults 18 years or older, including pregnant and postpartum women'
    SNOMEDCT = {'133931000119108', '703136005', '714035009'}
    ICD10CM = {'Z33.1', 'O80', 'Z39.2'}

class Adolescents(ValueSet):
    VALUE_SET_NAME = 'Adolescents'
    SNOMEDCT = {'67822003'}
    ICD10CM = {'Z00.3'}

def in_denominator(patient: Patient) -> bool:
    current_date = arrow.now()
    age = patient.age_at(current_date)
    if age >= 18:
        return True
    elif age >= 10 and age < 18:
        return True
    else:
        return False
class AdolescentsExclusion(ValueSet):
    VALUE_SET_NAME = 'Adolescents Exclusion Criteria'
    ICD10CM = {'Z00.129', 'Z00.121'}

class SettingsWithNoTreatmentOrPunitiveOutcomeExclusion(ValueSet):
    VALUE_SET_NAME = 'Settings With No Treatment or Punitive Outcomes Exclusion Criteria'
    SNOMEDCT = {'105480006', '237630007'}
    ICD10CM = {'Z59.7', 'Z59.5'}

def in_numerator(patient: Patient) -> bool:
    if patient.age_at(time=None) < 18:
        return False
    settings_check = False
    if settings_check:
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

class AdultsScreeningNIDAQuickScreen(ValueSet):
    VALUE_SET_NAME = 'Screening for Substance Use in Adults using NIDA Quick Screen'
    SNOMEDCT = {'123456', '234567', '345678', '456789', '567890', '678901', '789012', '890123', '901234', '012345'}
    LOINC = {'54321-0', '65432-1', '76543-2', '87654-3', '98765-4', '09876-5', '10987-6', '21098-7', '32109-8', '43210-9'}

class AdultsScreeningASSIST(ValueSet):
    VALUE_SET_NAME = 'Screening for Substance Use in Adults using ASSIST'
    SNOMEDCT = {'112233', '223344', '334455', '445566', '556677', '667788', '778899', '889900', '990011', '001122'}
    LOINC = {'12345-6', '23456-7', '34567-8', '45678-9', '56789-0', '67890-1', '78901-2', '89012-3', '90123-4', '01234-5'}

class PregnantScreeningPRO(ValueSet):
    VALUE_SET_NAME = 'Screening for Substance Use in Pregnant People using PRO (Prenatal Risk Overview)'
    SNOMEDCT = {'987654', '876543', '765432', '654321', '543210', '432109', '321098', '210987', '109876', '098765'}
    LOINC = {'56789-1', '67890-2', '78901-3', '89012-4', '90123-5', '01234-6', '12345-7', '23456-8', '34567-9', '45678-0'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_age = patient.age_at(arrow.now())
    if current_age >= 18:
        result.add_recommendation(title='NIDA Quick Screen', description='Screening for substance use with NIDA Quick Screen. No specific frequency recommended due to insufficient evidence.')
        result.add_recommendation(title='ASSIST', description='Screening for substance use with ASSIST. No specific frequency recommended due to insufficient evidence.')
    if hasattr(patient, 'is_pregnant') and patient.is_pregnant:
        result.add_recommendation(title='PRO (Prenatal Risk Overview)', description='Screening for substance use in pregnant people with PRO. No specific frequency recommended due to insufficient evidence.')
    return result

class UnhealthyDrugUseScreeningUSPSTF(ClinicalQualityMeasure):
    class Meta:
        title = "Unhealthy Drug Use Screening"
        description = "USPSTF recommendations on screening for unhealthy drug use in adults and adolescents"
        version = "v20240525093144"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240525093144"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.REFERRAL_REPORT]

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
