import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, PerformRecommendation
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2020 import GeneralSurgery, SuicideRiskAssessment
from canvas_workflow_kit.value_set.v2021 import Pregnancy
from canvas_workflow_kit.value_set.v2021.procedure import FollowUpForAboveNormalBmi
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesEstablishedOfficeVisit18AndUp
from canvas_workflow_kit.value_set.v2021.patient_characteristic import FrailtySymptom

class GastricPainValueSet(ValueSet): pass
class AntacidUseValueSet(ValueSet): pass
class RiskFactorsValueSet(ValueSet): pass
class AlarmSymptomsValueSet(ValueSet): pass
class DiagnosticInterventionsValueSet(ValueSet): pass

class GastricPainProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.age_at(arrow.now()) >= 18 and
                    len(self.patient.conditions.find(GastricPainValueSet)) > 0)

    def in_denominator(self) -> bool:
        persistent_pain = self.patient.conditions.find(GastricPainValueSet)
        no_relief = self.patient.medications.find(AntacidUseValueSet)
        return bool(len(persistent_pain) > 0 and len(no_relief) > 0)

    def in_numerator(self) -> bool:
        no_risk_factors = len(self.patient.conditions.find(RiskFactorsValueSet)) == 0
        no_alarm_symptoms = len(self.patient.conditions.find(AlarmSymptomsValueSet)) == 0
        no_surgery = len(self.patient.procedures.find(GeneralSurgery)) == 0
        not_pregnant = len(self.patient.conditions.find(Pregnancy)) == 0
        interventions = self.patient.procedures.find(DiagnosticInterventionsValueSet)
        return bool(no_risk_factors and no_alarm_symptoms and no_surgery and not_pregnant and len(interventions) > 0)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE
        result.add_narrative('Evaluate persistent gastric pain and lack of relief.')
        if not self.in_numerator():
            if len(self.patient.conditions.find(RiskFactorsValueSet)) > 0:
                result.add_recommendation(DiagnoseRecommendation(
                    key='risk_factors',
                    condition=RiskFactorsValueSet,
                    title='Evaluate Risk Factors',
                    narrative='Assess and document any risk factors for gastric conditions.',
                    patient=self.patient
                ))
            if len(self.patient.conditions.find(AlarmSymptomsValueSet)) > 0:
                result.add_recommendation(DiagnoseRecommendation(
                    key='alarm_symptoms',
                    condition=AlarmSymptomsValueSet,
                    title='Evaluate Alarm Symptoms',
                    narrative='Assess and document any alarm symptoms such as weight loss or bleeding.',
                    patient=self.patient
                ))
            if len(self.patient.procedures.find(GeneralSurgery)) > 0:
                result.add_recommendation(DiagnoseRecommendation(
                    key='surgery_history',
                    condition=GeneralSurgery,
                    title='Evaluate Surgery History',
                    narrative='Assess and document any history of gastric surgery.',
                    patient=self.patient
                ))
            if len(self.patient.conditions.find(Pregnancy)) > 0:
                result.add_recommendation(DiagnoseRecommendation(
                    key='pregnancy',
                    condition=Pregnancy,
                    title='Evaluate Pregnancy Status',
                    narrative='Assess and document pregnancy status.',
                    patient=self.patient
                ))
            if len(self.patient.procedures.find(DiagnosticInterventionsValueSet)) == 0:
                result.add_recommendation(PerformRecommendation(
                    key='diagnostic_interventions',
                    procedure=DiagnosticInterventionsValueSet,
                    title='Perform Diagnostic Interventions',
                    narrative='Conduct diagnostic interventions to identify the cause of gastric pain.',
                    patient=self.patient
                ))
        return result