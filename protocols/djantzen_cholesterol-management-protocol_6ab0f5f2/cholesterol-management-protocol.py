import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.patient_recordset import PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import EssentialHypertension, FindingOfElevatedBloodPressureOrHypertension, Diabetes, CurrentTobaccoSmoker, Pregnancy
from canvas_workflow_kit.value_set.v2018 import Trauma
from canvas_workflow_kit.value_set.v2020 import UrologicalSurgery
from canvas_workflow_kit.value_set.v2018 import PostoperativeVisit
from canvas_workflow_kit.value_set.v2021.lab_test import LdlCholesterol
from canvas_workflow_kit.recommendation import LabRecommendation, InstructionRecommendation, FollowUpRecommendation

class Hyperlipidemia(ValueSet):
    pass

class CardiovascularDisease(ValueSet):
    pass

class StatinAllergy(ValueSet):
    pass

class CholesterolTest(ValueSet):
    pass

class CholesterolManagementProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.age_at(self.now) >= 20 and
                    len(self.patient.conditions.find(Hyperlipidemia)) == 0 and
                    len(self.patient.conditions.find(CardiovascularDisease)) == 0)

    def in_denominator(self) -> bool:
        hypertension = self.patient.conditions.find(EssentialHypertension).find(FindingOfElevatedBloodPressureOrHypertension)
        return bool(self.in_initial_population() and
                    (len(hypertension) > 0 or
                     len(self.patient.conditions.find(Diabetes)) > 0 or
                     self.patient.vital_signs.filter(loincNum='39156-5').last_value(float) >= 25 or
                     len(self.patient.conditions.find(CurrentTobaccoSmoker)) > 0 or
                     self.patient.is_sedentary))

    def in_numerator(self) -> bool:
        cholesterol_tests = self.patient.lab_reports.find(CholesterolTest).after(self.timeframe.start)
        if len(cholesterol_tests) == 0:
            return False
        total_cholesterol = cholesterol_tests.filter(loincNum='2093-3').last_value(float)
        ldl_cholesterol = cholesterol_tests.find(LdlCholesterol).last_value(float)
        hdl_cholesterol = cholesterol_tests.filter(loincNum='2085-9').last_value(float)
        triglycerides = cholesterol_tests.filter(loincNum='2571-8').last_value(float)
        return bool(total_cholesterol < 200 and
                    ldl_cholesterol < 100 and
                    ((self.patient.is_male and hdl_cholesterol > 40) or
                     (self.patient.is_female and hdl_cholesterol > 50)) and
                    triglycerides < 150)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Cholesterol levels are within normal range.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Abnormal cholesterol levels detected.')
                result.add_recommendation(LabRecommendation(
                    key='cholesterol_test',
                    lab=CholesterolTest,
                    condition=None,
                    title='Order Cholesterol Test',
                    narrative='Recommend ordering a cholesterol test to evaluate lipid levels.',
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='lifestyle_modification',
                    instructions='Recommend lifestyle modifications to improve cholesterol levels.',
                    title='Provide Lifestyle Instructions',
                    narrative='Provide instructions on diet and exercise to improve cholesterol levels.',
                    patient=self.patient
                ))
                result.add_recommendation(FollowUpRecommendation(
                    key='cholesterol_follow_up',
                    title='Schedule Follow-Up',
                    narrative='Recommend follow-up to reassess cholesterol levels.',
                    patient=self.patient
                ))
        return result