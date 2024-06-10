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
class NewlyDiagnosedMultipleSclerosis(ValueSet):
    ICD10CM = {'G35'}
    SNOMEDCT = {'24700007', '85007004'}

class MultipleSclerosisForDMT(ValueSet):
    ICD10CM = {'G35'}
    SNOMEDCT = {'24700007', '85007004'}

class FirstDemyelinatingEventHighRiskMS(ValueSet):
    ICD10CM = {'G35', 'R90.89'}
    SNOMEDCT = {'24700007', '85007004', '427295001'}

class CISOrRelapsingMSNotOnDMT(ValueSet):
    ICD10CM = {'G35', 'G37.9'}
    SNOMEDCT = {'24700007', '85007004', '34000006'}

class WomenMSChildbearingPotential(ValueSet):
    ICD10CM = {'G35', 'Z32.01'}
    SNOMEDCT = {'24700007', '85007004', '77386006'}

class MenMSConsideringTeriflunomideOrCyclophosphamide(ValueSet):
    ICD10CM = {'G35'}
    SNOMEDCT = {'24700007', '85007004'}
    RXNORM = {'1248831', '198050'}

def in_denominator(patient: Patient) -> bool:
    if patient.conditions.find(NewlyDiagnosedMultipleSclerosis | MultipleSclerosisForDMT):
        return True
    if patient.conditions.find(FirstDemyelinatingEventHighRiskMS):
        return True
    if patient.conditions.find(CISOrRelapsingMSNotOnDMT):
        return True
    if patient.is_female and patient.conditions.find(WomenMSChildbearingPotential):
        return True
    if patient.is_male and patient.conditions.find(MenMSConsideringTeriflunomideOrCyclophosphamide):
        return True
    return False
class ExcludedPatients1(ValueSet):
    VALUE_SET_NAME = 'Excluded Patients with Incident Demyelinating Event and No Brain Lesions'
    ICD10CM = {'G37.3', 'G35', 'G36.0', 'G36.1', 'G36.9', 'G37.9', 'G40.9', 'G04.9', 'G37.4', 'G37.5'}

class ExcludedPatients2(ValueSet):
    VALUE_SET_NAME = 'Excluded Patients with CIS or Relapsing MS Without Recent Activity'
    ICD10CM = {'G35', 'G36.0', 'G36.1', 'G36.9', 'G37.9', 'G40.9', 'G04.9', 'G37.4', 'G37.5', 'G37.3'}

def in_numerator(patient: Patient) -> bool:
    if patient.conditions.find(ExcludedPatients1).exists():
        if not patient.imaging_reports.find(BrainLesions).exists():
            return True
    if patient.conditions.find(ExcludedPatients2).exists():
        if not patient.conditions.find(RelapsesInLastTwoYears).exists() and (not patient.imaging_reports.find(NewMRILesions).exists()):
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

class NewlyDiagnosedMultipleSclerosisCounseling(ValueSet):
    VALUE_SET_NAME = 'Counseling for Newly Diagnosed Multiple Sclerosis on DMT Options'

class MultipleSclerosisDMTConsideration(ValueSet):
    VALUE_SET_NAME = 'Evaluating Patient Preferences for DMT in Multiple Sclerosis'

class MultipleSclerosisOnDMTCounseling(ValueSet):
    VALUE_SET_NAME = 'Counseling for Multiple Sclerosis Patients on DMT'

class MultipleSclerosisDMTInitiationCounseling(ValueSet):
    VALUE_SET_NAME = 'Counseling on DMT Initiation for Multiple Sclerosis'

class MultipleSclerosisReproductiveCounseling(ValueSet):
    VALUE_SET_NAME = 'Reproductive Counseling for Women with Multiple Sclerosis on DMT'

class MultipleSclerosisMenReproductiveCounseling(ValueSet):
    VALUE_SET_NAME = 'Reproductive Counseling for Men with Multiple Sclerosis on Specific DMTs'

def recommendations(patient: Patient) -> ComposerResult:
    result = ComposerResult(patient)
    result.add_task('Counseling on DMT Options', 'Provide counseling about specific treatment options with DMT at a dedicated treatment visit.')
    result.add_task('Evaluate Patient Preferences for DMT', 'Evaluate patient preferences in terms of safety, route of administration, lifestyle, cost, efficacy, common adverse effects, and tolerability.')
    result.add_task('Counsel to Notify Clinicians of Symptoms', 'Counsel patients to notify clinicians of new or worsening symptoms.')
    result.add_task('Evaluate Readiness for DMT', 'Evaluate readiness or reluctance to initiate DMT and counsel on its importance.')
    result.add_task('Monitor Reproductive Plans', 'Monitor reproductive plans and counsel regarding reproductive risks and use of birth control during DMT use.')
    result.add_task('Counsel on Reproductive Plans for Men', 'Counsel on reproductive plans regarding treatment implications for men considering treatment with teriflunomide or cyclophosphamide.')
    return result

class MSDiseaseModifyingTherapiesGuide(ClinicalQualityMeasure):
    class Meta:
        title = "MS Therapies Guideline"
        description = "Summary of guideline recommendations for disease-modifying therapies in adults with multiple sclerosis"
        version = "v20240610094850"
        information = 'https://www.canvasmedical.com/'
        identifiers = ["AUTO20240610094850"]
        types = ['CQM']
        compute_on_change_types = [CHANGE_TYPE.CONDITION,CHANGE_TYPE.MEDICATION,CHANGE_TYPE.PRESCRIPTION,CHANGE_TYPE.LAB_REPORT,CHANGE_TYPE.IMAGING_REPORT]

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
