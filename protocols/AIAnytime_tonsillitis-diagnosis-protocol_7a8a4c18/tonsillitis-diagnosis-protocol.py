import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2020 import GeneralSurgery
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, ReferRecommendation, AllergyRecommendation

class TonsillitisValueSet(ValueSet):
    pass

class SoreThroatValueSet(ValueSet):
    pass

class FeverValueSet(ValueSet):
    pass

class SwollenTonsilsValueSet(ValueSet):
    pass

class DifficultySwallowingValueSet(ValueSet):
    pass

class RecurrentTonsillitisValueSet(ValueSet):
    pass

class PeritonsillarAbscessValueSet(ValueSet):
    pass

class ImmunocompromisedValueSet(ValueSet):
    pass

class AntibioticAllergyValueSet(ValueSet):
    pass

class TonsillitisDiagnosisProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        if not (self.patient.age_at(arrow.now()) >= 3):
            return False
        symptoms = self.patient.reason_for_visits.find(SoreThroatValueSet | FeverValueSet | SwollenTonsilsValueSet | DifficultySwallowingValueSet)
        if len(symptoms) < 2:
            return False
        recent_symptoms = symptoms.after(arrow.now().shift(days=-10))
        if len(recent_symptoms) == 0:
            return False
        return True

    def in_numerator(self) -> bool:
        exclusions = self.patient.conditions.find(RecurrentTonsillitisValueSet | PeritonsillarAbscessValueSet | ImmunocompromisedValueSet)
        if len(exclusions) > 0:
            return False
        if len(self.patient.allergy_intolerances.find(AntibioticAllergyValueSet)) > 0:
            return False
        recent_antibiotics = self.patient.medications.find(TonsillitisValueSet).after(arrow.now().shift(weeks=-2))
        if len(recent_antibiotics) > 0:
            return False
        return True

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE
        if not self.in_numerator():
            diagnose_recommendation = DiagnoseRecommendation(
                key='tonsillitis_diagnosis',
                condition=ValueSet(),
                title='Diagnose Tonsillitis',
                narrative='Consider diagnosing tonsillitis based on symptoms.',
                patient=self.patient
            )
            refer_recommendation = ReferRecommendation(
                key='refer_ent',
                referral=GeneralSurgery,
                title='Refer to ENT Specialist',
                narrative='Refer to ENT specialist for recurrent tonsillitis or abscess.',
                patient=self.patient
            )
            allergy_recommendation = AllergyRecommendation(
                key='antibiotic_allergy',
                allergy=AntibioticAllergyValueSet,
                title='Review Antibiotic Allergy',
                narrative='Review and manage known antibiotic allergy.',
                patient=self.patient
            )
            result.add_recommendation(diagnose_recommendation)
            result.add_recommendation(refer_recommendation)
            result.add_recommendation(allergy_recommendation)
        return result