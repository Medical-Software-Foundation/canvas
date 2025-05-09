import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import ReferRecommendation, DiagnoseRecommendation, InstructionRecommendation
from canvas_workflow_kit.value_set.v2022 import VaricellaZoster, Lupus, Measles

class DermatologyVisitValueSet(ValueSet):
    pass

class SkinCancerScreeningValueSet(ValueSet):
    pass

class SkinLesionValueSet(ValueSet):
    pass

class SkinCancerProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        age_20_39 = 20 <= self.patient.age_at(self.now) <= 39
        age_40_plus = self.patient.age_at(self.now) >= 40

        if age_20_39:
            three_years_ago = self.now.shift(years=-3)
            recent_screening = self.patient.procedures.find(SkinCancerScreeningValueSet).after(three_years_ago)
            recent_dermatology = self.patient.reason_for_visits.find(DermatologyVisitValueSet).after(three_years_ago)
            return len(recent_screening) == 0 and len(recent_dermatology) == 0

        if age_40_plus:
            one_year_ago = self.now.shift(years=-1)
            recent_screening = self.patient.procedures.find(SkinCancerScreeningValueSet).after(one_year_ago)
            recent_dermatology = self.patient.reason_for_visits.find(DermatologyVisitValueSet).after(one_year_ago)
            return len(recent_screening) == 0 and len(recent_dermatology) == 0

        return False

    def in_numerator(self) -> bool:
        fair_skin_features = self.patient.conditions.find(ValueSet()).has_feature('fair_skin')
        more_than_50_moles = self.patient.conditions.find(ValueSet()).has_feature('many_moles')
        family_history_melanoma = self.patient.conditions.find(ValueSet()).has_feature('family_melanoma')
        personal_history_skin_cancer = self.patient.conditions.find(ValueSet()).has_feature('personal_skin_cancer')
        sun_exposure = self.patient.conditions.find(ValueSet()).has_feature('sun_exposure')
        blistering_sunburns = self.patient.conditions.find(ValueSet()).has_feature('blistering_sunburns')

        no_new_changing_lesion = len(self.patient.reason_for_visits.find(SkinLesionValueSet)) == 0
        no_rash = len(self.patient.reason_for_visits.find(VaricellaZoster | Lupus | Measles)) == 0

        return (fair_skin_features or more_than_50_moles or family_history_melanoma or
                personal_history_skin_cancer or sun_exposure or blistering_sunburns) and no_new_changing_lesion and no_rash

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE

        if not self.in_numerator():
            refer_recommendation = ReferRecommendation(
                key='skin_cancer_screening',
                title='Refer for Skin Cancer Screening',
                narrative='Recommend referring the patient for a skin cancer screening based on risk factors.',
                patient=self.patient
            )
            diagnose_recommendation = DiagnoseRecommendation(
                key='skin_cancer_risk',
                title='Diagnose Skin Cancer Risk',
                narrative='Diagnose the patient with elevated risk for skin cancer based on history and features.',
                patient=self.patient
            )
            instruction_recommendation = InstructionRecommendation(
                key='sun_protection',
                title='Provide Sun Protection Instructions',
                narrative='Instruct the patient on sun protection measures to reduce skin cancer risk.',
                patient=self.patient
            )
            result.add_recommendation(refer_recommendation)
            result.add_recommendation(diagnose_recommendation)
            result.add_recommendation(instruction_recommendation)

        return result