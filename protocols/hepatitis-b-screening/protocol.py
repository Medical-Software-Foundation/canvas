from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.patient import Patient
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
import arrow
from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.protocol import ClinicalQualityMeasure
from canvas_workflow_kit.protocol import STATUS_DUE
from canvas_workflow_kit.protocol import STATUS_SATISFIED
from canvas_workflow_kit.protocol import ProtocolResult
from canvas_workflow_kit.timeframe import Timeframe
class HighPrevalenceHBVCountries(ValueSet):
    VALUE_SET_NAME = 'Persons born in countries and regions with a high prevalence of HBV infection (≥2%)'
    SNOMEDCT = {'165775009', '408350003'}

class USBornHighPrevalenceParentHBV(ValueSet):
    VALUE_SET_NAME = 'US-born persons not vaccinated as infants whose parents were born in regions with a very high prevalence of HBV infection (≥8%)'
    SNOMEDCT = {'416471007', '408350003'}

class HIVPositivePersons(ValueSet):
    VALUE_SET_NAME = 'HIV-positive persons'
    ICD10CM = {'B20'}
    SNOMEDCT = {'86406008'}

class InjectionDrugUsePersons(ValueSet):
    VALUE_SET_NAME = 'Persons with injection drug use'
    SNOMEDCT = {'228395002', '228390000'}

class MenWhoHaveSexWithMen(ValueSet):
    VALUE_SET_NAME = 'Men who have sex with men'
    SNOMEDCT = {'38628009', '20430005'}

class HouseholdContactsOrSexualPartnersOfHBV(ValueSet):
    VALUE_SET_NAME = 'Household contacts or sexual partners of persons with HBV infection'
    SNOMEDCT = {'267258002', '160592001'}

def in_denominator(patient: Patient) -> bool:
    if patient.allergy_intolerances.find(HighPrevalenceHBVCountries):
        return True
    elif patient.allergy_intolerances.find(USBornHighPrevalenceParentHBV):
        return True
    elif patient.allergy_intolerances.find(HIVPositivePersons):
        return True
    elif patient.allergy_intolerances.find(InjectionDrugUsePersons):
        return True
    elif patient.allergy_intolerances.find(MenWhoHaveSexWithMen):
        return True
    elif patient.allergy_intolerances.find(HouseholdContactsOrSexualPartnersOfHBV):
        return True
    return False
def in_numerator(patient: Patient) -> bool:
    return False
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

class HepatitisBScreening(ValueSet):
    VALUE_SET_NAME = 'Hepatitis B Screening'
    LOINC = {'24362-6', '5196-1', '16935-9', '22322-2', '6941-9', '5195-3', '32222-6', '48345-3', '22418-8', '16936-7'}

class HepatitisBConfirmatoryTest(ValueSet):
    VALUE_SET_NAME = 'Hepatitis B Confirmatory Test'
    LOINC = {'5195-3', '6941-9', '22322-2', '32222-6', '48345-3', '22418-8', '16936-7', '24362-6', '5196-1', '16935-9'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    if is_from_high_hbv_prevalence_region(patient):
        result.add_recommendation('Hepatitis B Screening', 'Screen for Hepatitis B due to high prevalence region of origin.', HepatitisBScreening)
    if is_us_born_with_high_hbv_prevalence_parents(patient):
        result.add_recommendation('Hepatitis B Screening for US-born individuals with parents from high prevalence regions', 'Screen for Hepatitis B as the patient is US-born with parents from regions with a very high prevalence of HBV infection.', HepatitisBScreening)
    if is_hiv_positive(patient):
        result.add_recommendation('Hepatitis B Screening for HIV-positive persons', 'Screen for Hepatitis B as the patient is HIV-positive.', HepatitisBScreening)
    if has_injection_drug_use_history(patient):
        result.add_recommendation('Hepatitis B Screening for persons with injection drug use', 'Screen for Hepatitis B due to history of injection drug use.', HepatitisBScreening)
    if is_man_who_has_sex_with_men(patient):
        result.add_recommendation('Hepatitis B Screening for men who have sex with men', 'Screen for Hepatitis B as the patient is a man who has sex with men.', HepatitisBScreening)
    if has_close_contact_with_hbv_infected(patient):
        result.add_recommendation('Hepatitis B Screening for household contacts or sexual partners of persons with HBV infection', 'Screen for Hepatitis B due to close contact with HBV infected persons.', HepatitisBScreening)
    return result

class HBVScreeningUSPSTFRecommendation(ClinicalQualityMeasure):
    class Meta:
        title = "HBV Screening Recommendation"
        description = "USPSTF recommendation on screening for hepatitis B in at-risk adolescents and adults"
        version = "v20240528123907"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240528123907"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.IMMUNIZATION,CHANGE_TYPE.LAB_REPORT]

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
