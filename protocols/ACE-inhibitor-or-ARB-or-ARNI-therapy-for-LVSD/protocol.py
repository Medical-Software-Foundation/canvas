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
class AdultPatients(ValueSet):
    VALUE_SET_NAME = 'All patients aged 18 years and older'

class HeartFailureDiagnosis(ValueSet):
    VALUE_SET_NAME = 'Diagnosis of heart failure'
    ICD10CM = {'I50.1', 'I50.20', 'I50.21', 'I50.22', 'I50.23', 'I50.30', 'I50.31', 'I50.32', 'I50.33', 'I50.9'}

class LeftVentricularEjectionFractionBelow40(ValueSet):
    VALUE_SET_NAME = 'Current or prior left ventricular ejection fraction (LVEF) < 40%'
    ICD10CM = {'I50.1', 'I50.22', 'I50.23', 'I50.42', 'I50.43'}

def in_denominator(patient: Patient) -> bool:
    age_cutoff_date = arrow.now().shift(years=-18)
    if patient.age_at(age_cutoff_date) < 18:
        return False
    heart_failure_diagnosis = patient.conditions.find(HeartFailureDiagnosis)
    if heart_failure_diagnosis is None or len(heart_failure_diagnosis) == 0:
        return False
    lvef_below_40 = patient.conditions.find(LeftVentricularEjectionFractionBelow40)
    if lvef_below_40 is None or len(lvef_below_40) == 0:
        return False
    return True
class ACEInhibitorTherapy(ValueSet):
    VALUE_SET_NAME = 'ACE Inhibitor Therapy'
    RXNORM = {'197361', '197381', '197320', '197379', '197377', '197369', '197375', '197387', '197395', '197407'}

class ARBTherapy(ValueSet):
    VALUE_SET_NAME = 'Angiotensin II Receptor Blocker (ARB) Therapy'
    RXNORM = {'979484', '979467', '979478', '979471', '979475', '979480', '979490', '979493', '979496', '979499'}

class ARNITherapy(ValueSet):
    VALUE_SET_NAME = 'Angiotensin Receptor-Neprilysin Inhibitor (ARNI) Therapy'
    RXNORM = {'1658423', '1658425', '1658427'}

def in_numerator(patient: Patient) -> bool:
    combined_therapy = ACEInhibitorTherapy | ARBTherapy | ARNITherapy
    twelve_months_ago = arrow.now().shift(months=-12)
    prescriptions_last_12_months = patient.prescriptions.after(twelve_months_ago)
    if prescriptions_last_12_months.find(combined_therapy):
        return True
    return False
class ContraindicationsToIntoleranceACE_ARB_ARNI(ValueSet):
    VALUE_SET_NAME = 'Contraindications or Intolerance to ACE inhibitors, ARBs, or ARNIs'
    SNOMEDCT = {'1090191000000102', '1090211000000107', '294987001', '429814007', '716186003'}
    ICD10CM = {'T46.5X5A', 'T46.6X5A', 'E78.71', 'T88.7XXA', 'Z88.2'}

class EndStageRenalDiseaseOrDialysis(ValueSet):
    VALUE_SET_NAME = 'End-Stage Renal Disease (ESRD) or Dialysis'
    ICD10CM = {'N18.6', 'Z99.2', 'N18.5'}
    SNOMEDCT = {'46177005', '723188008', '431855005'}

class Hyperkalemia(ValueSet):
    VALUE_SET_NAME = 'Hyperkalemia'
    ICD10CM = {'E87.5'}
    SNOMEDCT = {'14140009', '109838007', '16693006'}

class HospiceOrLifeExpectancyLessThanAYear(ValueSet):
    VALUE_SET_NAME = 'Hospice Care or Life Expectancy of Less Than a Year'
    ICD10CM = {'Z51.5', 'Z76.89'}
    SNOMEDCT = {'418799008', '371827001', '225728008'}

def in_exclusions(patient: Patient) -> bool:
    exclusion_criteria = ContraindicationsToIntoleranceACE_ARB_ARNI | EndStageRenalDiseaseOrDialysis | Hyperkalemia | HospiceOrLifeExpectancyLessThanAYear
    return bool(patient.conditions.find(exclusion_criteria))
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

class HeartFailureDiagnosis(ValueSet):
    VALUE_SET_NAME = 'Heart Failure Diagnosis'
    ICD10CM = {'I50.1', 'I50.20', 'I50.21', 'I50.22', 'I50.23', 'I50.30', 'I50.31', 'I50.32', 'I50.33', 'I50.40'}

class ACEInhibitorTherapy(ValueSet):
    VALUE_SET_NAME = 'ACE Inhibitor Therapy'
    RXNORM = {'197361', '197381', '197320', '197369', '197375', '197397', '197389', '197393', '197383', '197365'}

class ARBTherapy(ValueSet):
    VALUE_SET_NAME = 'ARB Therapy'
    RXNORM = {'979484', '979467', '979478', '979471', '979475', '979461', '979465', '979469', '979463', '979459'}

class ARNITherapy(ValueSet):
    VALUE_SET_NAME = 'ARNI Therapy'
    RXNORM = {'1658423', '1658427', '1658431'}

def recommendations(patient: Patient) -> ComposerResult:
    composer_result = ComposerResult(patient)
    if patient.age_at(arrow.now()) >= 18:
        heart_failure_diagnosis = patient.conditions.find(HeartFailureDiagnosis)
        if heart_failure_diagnosis:
            composer_result.add_prescription(title='Prescribe ACE inhibitor or ARB or ARNI therapy', description='Patient is 18 years or older with a diagnosis of heart failure and a current or prior LVEF < 40%. Prescribe ACE inhibitor or ARB or ARNI therapy.', prescription=ACEInhibitorTherapy | ARBTherapy | ARNITherapy)
    return composer_result

class HFACERBARNITherapy(ClinicalQualityMeasure):
    class Meta:
        title = "HF ACEARBARNI Therapy"
        description = "Evaluates prescription of ACE inhibitor ARB or ARNI therapy to HF patients."
        version = "v20240611060651"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240611060651"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.ALLERGY_INTOLERANCE,CHANGE_TYPE.ALLERGY_INTOLERANCE,CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION,CHANGE_TYPE.LAB_REPORT]

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
