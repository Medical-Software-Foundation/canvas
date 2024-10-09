import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import HeartFailure, EssentialHypertension, FindingOfElevatedBloodPressureOrHypertension
from canvas_workflow_kit.value_set.v2021.medication import StatinAllergen
from canvas_workflow_kit.value_set.v2021.encounter_performed import OutpatientConsultation, OfficeVisit
from canvas_workflow_kit.recommendation import LabRecommendation, ReferRecommendation, PlanRecommendation

class EchocardiogramValueSet(ValueSet):
    pass

class BNPTestValueSet(ValueSet):
    pass

class ClinicalProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        active_hf_medications = self.patient.medications.find(StatinAllergen).find_active()
        return len(active_hf_medications) > 0

    def in_denominator(self) -> bool:
        hf_diagnosis = self.patient.conditions.find(HeartFailure).find_active()
        return len(hf_diagnosis) == 0

    def in_numerator(self) -> bool:
        other_uses = self.patient.conditions.find(EssentialHypertension | FindingOfElevatedBloodPressureOrHypertension).find_active()
        undergoing_evaluation = self.patient.referrals.find(OutpatientConsultation).after(arrow.now().shift(months=-6))
        if len(other_uses) > 0 or len(undergoing_evaluation) > 0:
            return False
        echocardiogram = self.patient.procedures.find(EchocardiogramValueSet).after(arrow.now().shift(years=-1))
        bnp_test = self.patient.lab_reports.find(BNPTestValueSet).after(arrow.now().shift(years=-1))
        return len(echocardiogram) > 0 or len(bnp_test) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
            return result
        if self.in_numerator():
            result.status = STATUS_SATISFIED
            result.add_narrative('Heart failure diagnosis confirmed and medication use is appropriate.')
        else:
            result.status = STATUS_DUE
            result.add_narrative('Further evaluation needed to confirm heart failure diagnosis.')
            result.add_recommendation(LabRecommendation(
                key='bnp_test',
                lab=BNPTestValueSet,
                condition=None,
                title='Order BNP Test',
                narrative='Order BNP test to evaluate heart failure.',
                patient=self.patient
            ))
            result.add_recommendation(ReferRecommendation(
                key='cardiologist_referral',
                referral=OutpatientConsultation,
                condition=None,
                title='Refer to Cardiologist',
                narrative='Refer to cardiologist for further evaluation of heart failure.',
                patient=self.patient
            ))
            result.add_recommendation(PlanRecommendation(
                key='follow_up_plan',
                title='Develop Follow-Up Plan',
                narrative='Develop a follow-up plan to monitor heart failure symptoms and medication use.',
                patient=self.patient
            ))
        return result