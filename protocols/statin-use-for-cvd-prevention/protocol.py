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
class CVD_RiskFactors(ValueSet):
    VALUE_SET_NAME = 'CVD Risk Factors'
    SNOMEDCT = {'44054006', '73211009', '38341003', '77176002'}

class CVD_RiskAssessment_10_or_Greater(ValueSet):
    VALUE_SET_NAME = 'CVD Risk Assessment 10% or Greater'
    SNOMEDCT = {'84946008', '133931009'}
    LOINC = {'30522-7'}

class CVD_RiskAssessment_7_5_to_LessThan_10(ValueSet):
    VALUE_SET_NAME = 'CVD Risk Assessment 7.5% to Less Than 10%'
    SNOMEDCT = {'84946008', '133931009'}
    LOINC = {'74728-7'}

def in_denominator(patient: Patient) -> bool:
    current_year = arrow.now().year
    age = current_year - patient.date_of_birth.year
    if not 40 <= age <= 75:
        return False
    has_risk_factors = patient.conditions.find(CVD_RiskFactors).exists()
    has_known_cvd = patient.conditions.find(KnownCVD).exists()
    has_high_cvd_risk = patient.lab_reports.find(CVD_RiskAssessment_10_or_Greater).exists()
    has_moderate_cvd_risk = patient.lab_reports.find(CVD_RiskAssessment_7_5_to_LessThan_10).exists()
    return has_risk_factors and (not has_known_cvd) and (has_high_cvd_risk or has_moderate_cvd_risk)
class ExcludedPatients1(ValueSet):
    VALUE_SET_NAME = 'Excluded Patients 1'
    ICD10CM = {'Z91.89', 'Z92.89', 'Z76.89'}
    SNOMEDCT = {'183932001', '416940007', '394539002'}
    CPT = {'99201', '99202', '99203'}
    HCPCS = {'G0297', 'G0298', 'G0299'}

class ExcludedPatients2(ValueSet):
    VALUE_SET_NAME = 'Excluded Patients 2'
    ICD10CM = {'Z88.1', 'Z88.2', 'Z88.3'}
    SNOMEDCT = {'428041000124106', '428061000124105', '428071000124103'}
    CPT = {'99211', '99212', '99213'}
    HCPCS = {'G0402', 'G0403', 'G0404'}

def in_numerator(patient: Patient) -> bool:
    if patient.conditions.find(ExcludedPatients1 | ExcludedPatients2).exists() or patient.procedures.find(ExcludedPatients1 | ExcludedPatients2).exists() or patient.medications.intersects(ExcludedPatients1 | ExcludedPatients2).exists():
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

class Dyslipidemia(ValueSet):
    VALUE_SET_NAME = 'Dyslipidemia'
    ICD10CM = {'E78.0', 'E78.1', 'E78.2', 'E78.4', 'E78.5'}
    SNOMEDCT = {'267431006', '13644009', '398036000', '75183008', '414029004'}

class Diabetes(ValueSet):
    VALUE_SET_NAME = 'Diabetes'
    ICD10CM = {'E10', 'E11', 'E13', 'E08', 'E09'}
    SNOMEDCT = {'46635009', '44054006', '31321000', '190331003', '73211009'}

class Hypertension(ValueSet):
    VALUE_SET_NAME = 'Hypertension'
    ICD10CM = {'I10', 'I11', 'I12', 'I13', 'I15'}
    SNOMEDCT = {'38341003', '59621000', '111583006', '73410007', '44128008'}

class Smoking(ValueSet):
    VALUE_SET_NAME = 'Smoking'
    SNOMEDCT = {'77176002', '266919005', '428041000124106', '8517006', '428071000124103'}
    ICD10CM = {'F17.210', 'F17.218', 'F17.220', 'F17.228', 'Z72.0'}

class StatinTherapy(ValueSet):
    VALUE_SET_NAME = 'Statin Therapy for CVD Prevention'
    RXNORM = {'312961', '314231', '855332', '197361', '153165'}
    SNOMEDCT = {'860975006', '860980001', '372782005', '860972002', '860984005'}

class CVDPrevention(ValueSet):
    VALUE_SET_NAME = 'CVD Prevention'
    ICD10CM = {'Z13.6', 'I82.401', 'I82.402', 'Z86.79', 'Z86.73'}
    SNOMEDCT = {'428191000124101', '428251000124109', '18286008', '275599009', '408580009'}

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    age = patient.age_at(arrow.now())
    if 40 <= age <= 75 and (not patient.conditions.find(CVDPrevention)):
        has_risk_factors = any([patient.conditions.find(Dyslipidemia), patient.conditions.find(Diabetes), patient.conditions.find(Hypertension), patient.conditions.find(Smoking)])
        estimated_cvd_risk = estimate_10_year_cvd_risk(patient)
        if has_risk_factors and estimated_cvd_risk >= 10:
            result.add_recommendation(title='Statin for Primary Prevention of CVD', description='Patient meets criteria for statin therapy for the primary prevention of CVD as determined by clinician.')
        elif has_risk_factors and 7.5 <= estimated_cvd_risk < 10:
            result.add_recommendation(title='Selective Offering of Statin for Primary Prevention of CVD', description='Consider selective offering of statin for the primary prevention of CVD based on individual patient preference, considering potential small benefit against potential harms and inconvenience.')
    return result

def estimate_10_year_cvd_risk(patient: Patient) -> float:
    return 8.5

class StatinCVDPreventionUSPSTF(ClinicalQualityMeasure):
    class Meta:
        title = "Statin Use CVD Prevention"
        description = "USPSTF guidelines on statin use for the primary prevention of CVD in adults without known CVD"
        version = "v20240524045328"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240524045328"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION]

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
