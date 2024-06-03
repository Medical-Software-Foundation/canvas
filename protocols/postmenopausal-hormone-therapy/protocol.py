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
class PostmenopausalPersons(ValueSet):
    VALUE_SET_NAME = 'Postmenopausal Persons'
    SNOMEDCT = {'373887005', '5291005'}
    ICD10CM = {'Z78.0', 'N95.1'}

class PersonsConsideringHormoneTherapyForPreventionOfChronicConditions(ValueSet):
    VALUE_SET_NAME = 'Persons Considering Hormone Therapy for the Prevention of Chronic Conditions'
    SNOMEDCT = {'428251008', '225358003'}
    ICD10CM = {'Z79.890'}
    ICD9CM = {'V07.4'}
    CPT = {'G0108'}
    HCPCS = {'S9449', 'S9452'}

def in_denominator(patient: Patient) -> bool:
    postmenopausal_records = patient.conditions.find(PostmenopausalPersons)
    if postmenopausal_records:
        return True
    hormone_therapy_consideration_records = patient.conditions.find(PersonsConsideringHormoneTherapyForPreventionOfChronicConditions)
    if hormone_therapy_consideration_records:
        return True
    return False
class ExcludedPatients1(ValueSet):
    VALUE_SET_NAME = 'Persons considering hormone therapy for the management of perimenopausal symptoms, such as hot flashes or vaginal dryness'
    SNOMEDCT = {'386585007', '267032009'}
    ICD10CM = {'N95.1', 'E28.319'}

class ExcludedPatients2(ValueSet):
    VALUE_SET_NAME = 'Persons who have had premature menopause (primary ovarian insufficiency) or surgical menopause'
    SNOMEDCT = {'371036007', '52781008'}
    ICD10CM = {'E28.310', 'Z98.51'}

def in_numerator(patient: Patient) -> bool:
    if patient.conditions.find(ExcludedPatients1 | ExcludedPatients2):
        return True
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

class PostmenopausalWithIntactUterus(ValueSet):
    VALUE_SET_NAME = 'Postmenopausal persons with an intact uterus'
    SNOMEDCT = {'371036007', '52702003', '44795003'}
    ICD10CM = {'Z78.0', 'Z87.310'}

class CombinedEstrogenProgestinTherapy(ValueSet):
    VALUE_SET_NAME = 'Combined estrogen and progestin hormone therapy'
    RXNORM = {'1364430', '998412'}
    SNOMEDCT = {'386692008'}

class PostmenopausalHysterectomy(ValueSet):
    VALUE_SET_NAME = 'Postmenopausal persons who have had a hysterectomy'
    SNOMEDCT = {'52702003', '44795003', '236077008'}
    ICD10CM = {'Z90.710', 'Z90.712'}

class EstrogenAloneTherapy(ValueSet):
    VALUE_SET_NAME = 'Estrogen alone hormone therapy'
    RXNORM = {'206101', '998488'}
    SNOMEDCT = {'387517004'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    result.add_recommendation(title='Hormone Therapy for Postmenopausal Persons with an Intact Uterus', description='Combined estrogen and progestin hormone therapy is not recommended for postmenopausal persons with an intact uterus.', recommendation=CombinedEstrogenProgestinTherapy)
    result.add_recommendation(title='Hormone Therapy for Postmenopausal Persons Who Have Had a Hysterectomy', description='Estrogen alone hormone therapy is not recommended for postmenopausal persons who have had a hysterectomy.', recommendation=EstrogenAloneTherapy)
    return result

class PostmenopausalHormoneTherapyRecommendation(ClinicalQualityMeasure):
    class Meta:
        title = "Hormone Therapy Recommendation"
        description = "USPTF advises against hormone therapy for chronic conditions prevention in postmenopausal persons."
        version = "v20240603044651"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240603044651"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PROCEDURE]

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
