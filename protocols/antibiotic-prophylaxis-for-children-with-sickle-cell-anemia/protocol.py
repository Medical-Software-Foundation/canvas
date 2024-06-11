from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.value_set import ValueSet
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
class SickleCellAnemiaDiagnosis(ValueSet):
    VALUE_SET_NAME = 'Sickle Cell Anemia Diagnosis for Children Ages 3 Months to 5 Years'
    ICD10CM = {'D57.00', 'D57.1', 'D57.20', 'D57.211', 'D57.212', 'D57.3', 'D57.40', 'D57.419', 'D57.80', 'D57.819'}

def in_denominator(patient: Patient) -> bool:
    current_year = arrow.now().year
    start_of_year = arrow.get(f'{current_year}-01-01')
    end_of_year = arrow.get(f'{current_year}-12-31')
    age_at_start_of_year = patient.age_at(start_of_year)
    age_at_end_of_year = patient.age_at(end_of_year)
    if not (0.25 <= age_at_start_of_year <= 5 or 0.25 <= age_at_end_of_year <= 5):
        return False
    sickle_cell_anemia_diagnoses = patient.conditions.find(SickleCellAnemiaDiagnosis)
    if sickle_cell_anemia_diagnoses:
        return True
    return False
class SickleCellAnemiaDiagnosis(ValueSet):
    VALUE_SET_NAME = 'Sickle Cell Anemia Diagnosis'
    ICD10CM = {'D57.00', 'D57.1', 'D57.20', 'D57.211', 'D57.3', 'D57.40', 'D57.419', 'D57.80', 'D57.811', 'D57.819'}

class AntibioticProphylaxis(ValueSet):
    VALUE_SET_NAME = 'Antibiotic Prophylaxis'
    RXNORM = {'312961', '197361', '308056', '860975', '197379', '312962', '153971', '1049502', '199692', '310798'}

def in_numerator(patient: Patient) -> bool:
    measurement_year_start = arrow.now().floor('year')
    measurement_year_end = arrow.now().ceil('year')
    age_in_months = patient.age_at(measurement_year_start) * 12
    if not 3 <= age_in_months <= 60:
        return False
    has_sca = patient.conditions.find(SickleCellAnemiaDiagnosis).before(measurement_year_end).after(measurement_year_start.shift(years=-1))
    if not has_sca:
        return False
    antibiotics_dispensed = patient.medications.find(AntibioticProphylaxis).intersects(Timeframe(measurement_year_start, measurement_year_end), still_active=False)
    total_days_covered = sum([record.days_supplied for record in antibiotics_dispensed])
    return total_days_covered >= 300
class NoDenominatorExclusions(ValueSet):
    VALUE_SET_NAME = 'No Denominator Exclusions'

def in_exclusions(patient: Patient) -> bool:
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

class SickleCellAnemiaDiagnosis(ValueSet):
    VALUE_SET_NAME = 'Sickle Cell Anemia Diagnosis'
    ICD10CM = {'D57.00', 'D57.1', 'D57.20', 'D57.211', 'D57.212', 'D57.3', 'D57.40', 'D57.419', 'D57.80', 'D57.819'}

class AntibioticProphylaxis(ValueSet):
    VALUE_SET_NAME = 'Antibiotic Prophylaxis'
    RXNORM = {'860975', '198211', '313782', '197361', '308056', '6960', '630208', '197379', '308192', '214199'}

class Age3MonthsTo5Years(ValueSet):
    VALUE_SET_NAME = 'Age 3 Months to 5 Years'
    SNOMEDCT = {'170357008', '170358003', '170359006', '170360001', '170361002', '170362009', '170363004', '170364005', '170365006', '445518008'}

def recommendations(patient: Patient) -> ComposerResult:
    composer_result = ComposerResult(patient)
    current_year = arrow.now().year
    start_of_year = arrow.get(f'{current_year}-01-01')
    end_of_year = arrow.get(f'{current_year}-12-31')
    patient_age_days = patient.age_at(arrow.now()) * 365.25
    if 3 * 30 <= patient_age_days <= 5 * 365.25:
        sickle_cell_anemia_records = patient.conditions.find(SickleCellAnemiaDiagnosis)
        if sickle_cell_anemia_records:
            antibiotic_prescriptions = patient.prescriptions.find(AntibioticProphylaxis).before(end_of_year).after(start_of_year)
            total_days_covered = sum([prescription.duration for prescription in antibiotic_prescriptions])
            if total_days_covered < 300:
                composer_result.add_prescription(title='Antibiotic Prophylaxis for Sickle Cell Anemia', description='Dispense appropriate antibiotic prophylaxis to children ages 3 months to 5 years old with sickle cell anemia for at least 300 days within the measurement year.', prescription=AntibioticProphylaxis)
    return composer_result

class AntibioticProphylaxisSCAMeasure(ClinicalQualityMeasure):
    class Meta:
        title = "Antibiotic Prophylaxis in Sickle Cell Anemia"
        description = "Assesses antibiotic prophylaxis in children 3 months to 5 years old with sickle cell anemia over a year"
        version = "v20240611041107"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240611041107"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION]

    def in_initial_population(self) -> bool:
        return not in_exclusions(self.patient)

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
