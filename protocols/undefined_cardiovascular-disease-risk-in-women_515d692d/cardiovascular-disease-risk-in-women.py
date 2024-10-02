import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, PlanRecommendation, ReferRecommendation
from canvas_workflow_kit.value_set import ValueSet

# Importing the defined ValueSet subclasses
from canvas_workflow_kit.value_set.v2020 import AnnualWellnessVisit, ContactOrOfficeVisit, DepressionScreeningEncounterCodes
from canvas_workflow_kit.value_set.v2021.diagnosis import EssentialHypertension, Diabetes, CurrentTobaccoSmoker, Cancer
from canvas_workflow_kit.value_set.v2021.encounter import EncounterToScreenForBloodPressure, EncounterToScreenForDepression
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesInitialOfficeVisit18AndUp, PreventiveCareServicesIndividualCounseling, OutpatientConsultation, PreventiveCareServicesEstablishedOfficeVisit18AndUp
from canvas_workflow_kit.value_set.v2021.procedure import BmiRatio

class MenopauseValueSet(ValueSet):
    pass

class HighHDLValueSet(ValueSet):
    pass

class KnownCVDValueSet(ValueSet):
    pass

class ChronicIllnessValueSet(ValueSet):
    pass

class CognitiveImpairmentValueSet(ValueSet):
    pass

class CVD_Risk_Evaluation(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.is_female and 40 <= self.patient.age_at(self.now) <= 75)

    def in_denominator(self) -> bool:
        menopause = len(self.patient.conditions.find(MenopauseValueSet)) > 0
        hypertension = len(self.patient.conditions.find(EssentialHypertension)) > 0
        diabetes = len(self.patient.conditions.find(Diabetes)) > 0
        smoking = len(self.patient.conditions.find(CurrentTobaccoSmoker)) > 0
        high_bmi = len(self.patient.procedures.find(BmiRatio)) > 0
        high_hdl = len(self.patient.conditions.find(HighHDLValueSet)) > 0
        return bool(menopause or hypertension or diabetes or smoking or high_bmi or high_hdl)

    def in_numerator(self) -> bool:
        known_cvd = len(self.patient.conditions.find(KnownCVDValueSet)) > 0
        breast_cancer = len(self.patient.conditions.find(Cancer)) > 0
        chronic_illness = len(self.patient.conditions.find(ChronicIllnessValueSet)) > 0
        cognitive_impairment = len(self.patient.conditions.find(CognitiveImpairmentValueSet)) > 0
        return bool(known_cvd or breast_cancer or chronic_illness or cognitive_impairment)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient is at high risk for CVD.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='cvd_diagnosis',
                    condition='Cardiovascular Disease',
                    diagnosis=DiagnoseRecommendation.Diagnosis(
                        condition='Cardiovascular Disease',
                        value_set=KnownCVDValueSet
                    ),
                    title='Diagnose CVD',
                    narrative='Diagnose cardiovascular disease based on known history.'
                ))
                result.add_recommendation(PlanRecommendation(
                    key='risk_management_plan',
                    title='Develop Risk Management Plan',
                    narrative='Develop a personalized plan to manage CVD risk.',
                    patient=self.patient
                ))
                result.add_recommendation(ReferRecommendation(
                    key='cardiology_referral',
                    referral=ReferRecommendation.Referral(
                        specialty='Cardiology',
                        condition='Cardiovascular Disease'
                    ),
                    title='Refer to Cardiologist',
                    narrative='Refer patient to a cardiologist for further evaluation.'
                ))
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient is not at high risk for CVD.')
        return result