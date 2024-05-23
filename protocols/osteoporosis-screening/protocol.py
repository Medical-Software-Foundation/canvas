from canvas_workflow_kit.value_set import ValueSet
import arrow
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
from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.protocol import ClinicalQualityMeasure
from canvas_workflow_kit.protocol import STATUS_DUE
from canvas_workflow_kit.protocol import STATUS_SATISFIED
from canvas_workflow_kit.protocol import ProtocolResult
from canvas_workflow_kit.timeframe import Timeframe
class Women65AndOlder(ValueSet):
    VALUE_SET_NAME = 'Women 65 years and older'
    SNOMEDCT = {'703138006'}
    ICD10CM = {'Z0154'}
    LOINC = {'8339-4'}

class PostmenopausalWomenYoungerThan65AtIncreasedRisk(ValueSet):
    VALUE_SET_NAME = 'Postmenopausal women younger than 65 years at increased risk of osteoporosis, as determined by a formal clinical risk assessment tool'
    SNOMEDCT = {'445528004', '313267000'}
    ICD10CM = {'M81.0', 'Z78.0'}
    LOINC = {'82810-3', '72166-2'}

def in_denominator(patient: Patient) -> bool:
    current_date = arrow.now()
    age = patient.age_at(current_date)
    if patient.is_female and age >= 65:
        return True
    return False
class ExcludedPatients1(ValueSet):
    VALUE_SET_NAME = 'Persons who take long-term medications that may cause secondary osteoporosis'
    RXNORM = {'855332', '197806', '259255', '198013', '692382', '602388', '1364430', '1114191', '1114190', '1114124'}

def in_numerator(patient: Patient) -> bool:
    """
    Determines if a patient meets the criteria for exclusion based on the use of long-term medications
    that may cause secondary osteoporosis.
    """
    return patient.medications.find(ExcludedPatients1).exists()
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

class CentralDXAScreening(ValueSet):
    VALUE_SET_NAME = 'Central Dual-energy X-ray Absorptiometry (DXA) Screening for Osteoporosis'
    CPT = {'77080', '77081'}
    ICD10CM = {'Z13.820'}
    SNOMEDCT = {'398829007', '312681000119105'}

class PeripheralDXAScreening(ValueSet):
    VALUE_SET_NAME = 'Peripheral Dual-energy X-ray Absorptiometry (DXA) Screening for Osteoporosis'
    CPT = {'77082'}
    ICD10CM = {'Z13.820'}
    SNOMEDCT = {'413815001', '312681000119105'}

class QuantitativeUltrasoundScreening(ValueSet):
    VALUE_SET_NAME = 'Quantitative Ultrasound (QUS) Screening for Osteoporosis'
    CPT = {'76977'}
    ICD10CM = {'Z13.820'}
    SNOMEDCT = {'441829005', '312681000119105'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_year = arrow.now().year
    patient_age = patient.age_at(arrow.now())
    is_postmenopausal_woman = patient.is_female and (patient_age >= 65 or (patient_age < 65 and 'at increased risk'))
    if is_postmenopausal_woman:
        result.add_recommendation(title='Central DXA Screening', description='Central dual-energy X-ray absorptiometry (DXA) screening is recommended. No specific interval recommended; screenings based on clinical judgment, patient preferences, and possibly transition time to osteoporosis as suggested by observational and modeling studies.')
        result.add_recommendation(title='Peripheral DXA Screening', description='Peripheral dual-energy X-ray absorptiometry (DXA) screening is recommended. No specific interval recommended; screenings based on clinical judgment, patient preferences, and possibly transition time to osteoporosis as suggested by observational and modeling studies.')
        result.add_recommendation(title='Quantitative Ultrasound (QUS) Screening', description='Quantitative Ultrasound (QUS) screening is recommended. No specific interval recommended; screenings based on clinical judgment, patient preferences, and possibly transition time to osteoporosis as suggested by observational and modeling studies.')
    return result

class OsteoporosisScreeningRecommendation(ClinicalQualityMeasure):
    class Meta:
        title = "Osteoporosis Screening"
        description = "USPSTF recommendation on screening for osteoporosis to prevent fractures"
        version = "v20240523153159"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240523153159"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.IMAGING_REPORT]

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
