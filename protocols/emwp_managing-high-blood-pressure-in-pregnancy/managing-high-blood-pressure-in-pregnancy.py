import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.lab_test import UrineProteinTests
from canvas_workflow_kit.value_set.v2021.diagnosis import (
    DiagnosisOfHypertension,
    EssentialHypertension,
    FindingOfElevatedBloodPressureOrHypertension,
    Diabetes,
    KidneyFailure,
    OverweightOrObese
)
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import TaskRecommendation, PlanRecommendation

class PregnancyValueSet(ValueSet):
    pass

class PreeclampsiaValueSet(ValueSet):
    pass

class AutoimmuneDisordersValueSet(ValueSet):
    pass

class MultipleGestationValueSet(ValueSet):
    pass

class SevereComorbidConditionsValueSet(ValueSet):
    pass

class FetalAnomaliesValueSet(ValueSet):
    pass

class PreeclampsiaScreeningMeasure(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        pregnancy_conditions = self.patient.conditions.find(PregnancyValueSet)
        hypertension_conditions = self.patient.conditions.find(DiagnosisOfHypertension)
        return (
            self.patient.is_female
            and self.patient.age_at(arrow.now()) >= 18
            and len(pregnancy_conditions) > 0
            and len(hypertension_conditions) > 0
        )

    def in_denominator(self) -> bool:
        preeclampsia_history = self.patient.conditions.find(PreeclampsiaValueSet)
        chronic_hypertension = self.patient.conditions.find(EssentialHypertension)
        diabetes = self.patient.conditions.find(Diabetes)
        renal_disease = self.patient.conditions.find(KidneyFailure)
        autoimmune_disorders = self.patient.conditions.find(AutoimmuneDisordersValueSet)
        multiple_gestation = self.patient.conditions.find(MultipleGestationValueSet)
        obesity = self.patient.conditions.find(OverweightOrObese)
        advanced_age = self.patient.age_at(arrow.now()) >= 35
        return (
            len(preeclampsia_history) > 0
            or len(chronic_hypertension) > 0
            or len(diabetes) > 0
            or len(renal_disease) > 0
            or len(autoimmune_disorders) > 0
            or len(multiple_gestation) > 0
            or len(obesity) > 0
            or advanced_age
        )

    def in_numerator(self) -> bool:
        contraindications = self.patient.conditions.find(SevereComorbidConditionsValueSet)
        fetal_anomalies = self.patient.conditions.find(FetalAnomaliesValueSet)
        return len(contraindications) == 0 and len(fetal_anomalies) == 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Preeclampsia screening completed successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Preeclampsia screening is due.')
                task_recommendation = TaskRecommendation(
                    key='contraindications_check',
                    title='Check for Contraindications',
                    narrative='Evaluate for contraindications to antihypertensive medications.',
                    patient=self.patient
                )
                plan_recommendation = PlanRecommendation(
                    key='fetal_anomalies_plan',
                    title='Plan for Fetal Anomalies',
                    narrative='Develop a plan for managing known fetal anomalies.',
                    patient=self.patient
                )
                result.add_recommendation(task_recommendation)
                result.add_recommendation(plan_recommendation)
        return result