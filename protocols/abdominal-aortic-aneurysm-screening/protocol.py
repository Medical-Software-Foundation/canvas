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
class MenAged65To75WhoHaveEverSmoked(ValueSet):
    pass

class MenAged65To75WhoHaveNeverSmoked(ValueSet):
    pass

class WomenAged65To75WhoHaveEverSmokedOrFamilyHistoryOfAAA(ValueSet):
    pass

class WomenAged65To75WhoHaveNeverSmokedAndNoFamilyHistoryOfAAA(ValueSet):
    pass

def in_denominator(patient: Patient) -> bool:
    current_time = arrow.now()
    age = patient.age_at(current_time)
    if not 65 <= age <= 75:
        return False
    if patient.is_male:
        if patient.smoking_status in [MenAged65To75WhoHaveEverSmoked, MenAged65To75WhoHaveNeverSmoked]:
            return True
    elif patient.is_female:
        if patient.smoking_status in [WomenAged65To75WhoHaveEverSmokedOrFamilyHistoryOfAAA, WomenAged65To75WhoHaveNeverSmokedAndNoFamilyHistoryOfAAA]:
            return True
    return False
class ScreeningNotOfferedUnableSurgicalIntervention(ValueSet):
    VALUE_SET_NAME = 'Screening Not Offered to Patients Unable to Undergo Surgical Intervention'
    SNOMEDCT = {'237618005', '183932001', '410536001', '304295008', '735439008', '183944003', '183945002', '310376006', '183928007', '183927002'}

class ScreeningNotOfferedReducedLifeExpectancy(ValueSet):
    VALUE_SET_NAME = 'Screening Not Offered to Patients with a Reduced Life Expectancy'
    SNOMEDCT = {'89242000', '52613005', '371827003', '161891005', '263502005', '431855005', '42343007', '442083009', '289908002', '705057003'}

def in_numerator(patient: Patient) -> bool:
    unable_surgical_intervention = patient.conditions.find(ScreeningNotOfferedUnableSurgicalIntervention)
    if unable_surgical_intervention:
        return False
    reduced_life_expectancy = patient.conditions.find(ScreeningNotOfferedReducedLifeExpectancy)
    if reduced_life_expectancy:
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

class Men_65_75_Ever_Smoked(ValueSet):
    VALUE_SET_NAME = 'Men aged 65 to 75 years who have ever smoked'
    SNOMEDCT = {'446096008', '703138006'}
    ICD10CM = {'Z87.891'}
    LOINC = {'72166-2'}

class Men_65_75_Never_Smoked(ValueSet):
    VALUE_SET_NAME = 'Men aged 65 to 75 years who have never smoked'
    SNOMEDCT = {'266919005', '703138006'}
    LOINC = {'11368-8'}

class Women_65_75_Never_Smoked_No_Family_History_AAA(ValueSet):
    VALUE_SET_NAME = 'Women aged 65 to 75 years who have never smoked and have no family history of AAA'
    SNOMEDCT = {'266919005', '703118005', '160273001'}
    ICD10CM = {'Z86.79'}

class Women_65_75_Ever_Smoked_Or_Family_History_AAA(ValueSet):
    VALUE_SET_NAME = 'Women aged 65 to 75 years who have ever smoked or have a family history of AAA'
    SNOMEDCT = {'446096008', '703118005', '416855002'}
    ICD10CM = {'Z87.891', 'Z82.3'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_year = arrow.now().year
    patient_age = patient.age_at(arrow.now())
    if patient.is_male and 65 <= patient_age <= 75:
        if patient.smoking_status == 'Ever smoked':
            result.add_recommendation(title='AAA Screening for Men 65-75 Who Have Ever Smoked', description='Recommend one-time screening for abdominal aortic aneurysm (AAA) via ultrasonography.')
        elif patient.smoking_status == 'Never smoked':
            result.add_recommendation(title='AAA Screening for Men 65-75 Who Have Never Smoked', description='Selectively offer screening for abdominal aortic aneurysm (AAA) via ultrasonography.')
    if patient.is_female and 65 <= patient_age <= 75:
        if patient.smoking_status == 'Never smoked' and (not patient.has_family_history_of_AAA):
            result.add_recommendation(title='AAA Screening for Women 65-75 Who Have Never Smoked with No Family History of AAA', description='Recommends against routine screening for abdominal aortic aneurysm (AAA).')
        elif patient.smoking_status == 'Ever smoked' or patient.has_family_history_of_AAA:
            result.add_recommendation(title='AAA Screening for Women 65-75 Who Have Ever Smoked or Have Family History of AAA', description='Evidence is insufficient to assess the balance of benefits and harms of screening for AAA.')
    return result

class AAA_USPSTF_Recommendation(ClinicalQualityMeasure):
    class Meta:
        title = "AAA Screening Recommendation"
        description = "USPSTF recommendation on abdominal aortic aneurysm screening for adults over 50"
        version = "v20240604110034"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240604110034"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.PROCEDURE,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.IMAGING_REPORT]

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
