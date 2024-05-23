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
class Newborns(ValueSet):
    VALUE_SET_NAME = 'Newborns'
    SNOMEDCT = {'276361009', '27641000119107', '276424009', '276606009', '276610007', '276612004', '276658003', '276709006', '276736001', '276737005'}

def in_denominator(patient: Patient) -> bool:
    return False
class NewbornScreening(ValueSet):
    VALUE_SET_NAME = 'Newborn Screening for Gonococcal Ophthalmia Neonatorum'
    ICD10CM = {'P38.1'}
    SNOMEDCT = {'276549000', '409656007'}
    LOINC = {'14463-4', '20416-4'}
    CPT = {'87850'}
    HCPCS = {'G0475'}

class NewbornExclusionCriteria(ValueSet):
    VALUE_SET_NAME = 'Newborn Exclusion Criteria for Screening'

def in_numerator(patient: Patient) -> bool:
    """
    Determines if a patient meets the criteria to be screened for gonococcal ophthalmia neonatorum.
    Since there are no specific exclusion criteria provided for newborns regarding the screening,
    this function will always return True, indicating all newborns should be screened.
    """
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

class NewbornScreening(ValueSet):
    VALUE_SET_NAME = 'Newborn Screening for Ophthalmia Neonatorum Prophylaxis'
    ICD10CM = {'Z38.00', 'Z38.01', 'Z38.2', 'Z38.3', 'Z38.60', 'Z38.61', 'Z38.8', 'P23.9', 'P35.0', 'P37.3'}
    SNOMEDCT = {'77465009', '56265001', '18286008', '103693007', '27658006', '416940007', '410534003', '424673000', '276746005', '71388002'}

class OphthalmicOintment(ValueSet):
    VALUE_SET_NAME = '0.5% Erythromycin Ophthalmic Ointment for Newborns'
    RXNORM = {'1049221', '310965', '998456', '8591', '197379'}
    SNOMEDCT = {'416940007', '703938007', '410534003', '424673000', '276746005'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    result.add_task(title='Administer 0.5% Erythromycin Ophthalmic Ointment', description='Apply a single dose of 0.5% erythromycin ophthalmic ointment to each eye of the newborn immediately after birth to prevent ophthalmia neonatorum.')
    return result

class GonococcalOphthalmiaProphylaxis(ClinicalQualityMeasure):
    class Meta:
        title = "Gonococcal Ophthalmia Neonatorum"
        description = "USPSTF reaffirmation on neonatal ocular prophylaxis for gonococcal infection prevention"
        version = "v20240417084556"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240417084556"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.ALLERGY_INTOLERANCE,CHANGE_TYPE.ALLERGY_INTOLERANCE,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION]

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
