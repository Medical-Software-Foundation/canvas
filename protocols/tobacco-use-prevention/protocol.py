from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.value_set import ValueSet
import arrow
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.patient_recordset import PatientPeriodRecordSet
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
class SchoolAgedChildren(ValueSet):
    VALUE_SET_NAME = 'School-aged Children'
    ICD10CM = {'Z00.129', 'J00', 'J20.9', 'K00.2', 'B08.5'}
    SNOMEDCT = {'27658006', '410607006', '224930009', '70036007', '41729002'}

class AdolescentsUnder18(ValueSet):
    VALUE_SET_NAME = 'Adolescents Younger Than 18 Years'
    ICD10CM = {'Z00.121', 'F91.9', 'F32.9', 'J45.909', 'E66.9'}
    SNOMEDCT = {'133931009', '414564002', '195967001', '141441000119107', '409623005'}

def in_denominator(patient: Patient) -> bool:
    current_date = arrow.now()
    age = patient.age_at(current_date)
    return age < 18
class SevereAllergies(ValueSet):
    pass

class ChronicConditions(ValueSet):
    pass

class RecentSurgery(ValueSet):
    pass
EXCLUDED_PATIENTS = {'allergies': SevereAllergies, 'conditions': ChronicConditions, 'procedures': RecentSurgery}

def in_numerator(patient: Patient) -> bool:
    if patient.allergy_intolerances.find(EXCLUDED_PATIENTS['allergies']).before(end=arrow.now()):
        return False
    if patient.conditions.intersects(Timeframe(start=arrow.get(patient.date_of_birth), end=arrow.now()), still_active=True):
        return False
    one_year_ago = arrow.now().shift(years=-1)
    if patient.procedures.before(end=arrow.now()).after(start=one_year_ago):
        return False
    return True
print(EXCLUDED_PATIENTS)
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

class SchoolAgedChildrenAndAdolescentsScreeningFaceToFaceOrTelephone(ValueSet):
    VALUE_SET_NAME = 'School-Aged Children and Adolescents Screening via Face-to-Face or Telephone Interaction'
    SNOMEDCT = {'185317003', '410620009', '410621008', '424673000', '698314001', '185349003', '225358003', '410604004', '424308004', '410605003'}

class SchoolAgedChildrenAndAdolescentsScreeningPrintMaterials(ValueSet):
    VALUE_SET_NAME = 'School-Aged Children and Adolescents Screening via Print Materials'
    SNOMEDCT = {'385763005', '385764004', '385765003', '385766002', '385767006', '385768001', '385769009', '385770000', '385771001', '385772008'}

class SchoolAgedChildrenAndAdolescentsScreeningComputerApplications(ValueSet):
    VALUE_SET_NAME = 'School-Aged Children and Adolescents Screening via Computer Applications'
    SNOMEDCT = {'736271009', '736272002', '736273007', '736274001', '736275000', '736276004', '736277008', '736278003', '736279006', '736280009'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    current_age = patient.age_at(arrow.now())
    if 5 <= current_age <= 18:
        result.add_recommendation(title='Face-to-Face or Telephone Interaction Screening', description='Consider scheduling a face-to-face or telephone interaction screening with a healthcare clinician.')
        result.add_recommendation(title='Print Materials Screening', description='Provide print materials for screening purposes, which can include information leaflets or medication guides.')
        result.add_recommendation(title='Computer Applications Screening', description='Utilize computer applications for screening, which can support disease management, health and wellness, or clinical decision support.')
    return result

class TobaccoUsePreventionYouth(ClinicalQualityMeasure):
    class Meta:
        title = "Tobacco Use Prevention"
        description = "USPSTF recommendations on preventing and stopping tobacco use in youth"
        version = "v20240525090400"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240525090400"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION]

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
