import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.rationale import MedicalReason
from canvas_workflow_kit.value_set.v2021.assessment import TobaccoUseScreening
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit, ContactOrOfficeVisit
from canvas_workflow_kit.value_set.v2021.encounter import BehavioralHealthFollowUpVisit, PsychVisitPsychotherapy
from canvas_workflow_kit.recommendation import DiagnoseRecommendation, InstructionRecommendation, PlanRecommendation

class PruritusValueSet(ValueSet):
    pass

class EczematousLesionsValueSet(ValueSet):
    pass

class DermatitisHistoryValueSet(ValueSet):
    pass

class AtopyFamilyHistoryValueSet(ValueSet):
    pass

class OtherDermatologicalConditionsValueSet(ValueSet):
    pass

class HypersensitivityValueSet(ValueSet):
    pass

class SkinInfectionsValueSet(ValueSet):
    pass

class ClinicalTrialValueSet(ValueSet):
    pass

class EczemaDiagnosisValueSet(ValueSet):
    pass

class EczemaTreatmentValueSet(ValueSet):
    pass

class EczemaProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(self.patient.age_at(arrow.now()) < 18)

    def in_denominator(self) -> bool:
        pruritus = self.patient.interviews.find(PruritusValueSet)
        lesions = self.patient.conditions.find(EczematousLesionsValueSet)
        history = self.patient.conditions.find(DermatitisHistoryValueSet)
        family_history = self.patient.conditions.find(AtopyFamilyHistoryValueSet)
        return bool(pruritus and lesions and history and family_history)

    def in_numerator(self) -> bool:
        other_conditions = self.patient.conditions.find(OtherDermatologicalConditionsValueSet)
        hypersensitivity = self.patient.allergy_intolerances.find(HypersensitivityValueSet)
        infections = self.patient.conditions.find(SkinInfectionsValueSet)
        immunocompromised = self.patient.conditions.find(MedicalReason)
        clinical_trial = self.patient.conditions.find(ClinicalTrialValueSet)
        if any([other_conditions, hypersensitivity, infections, immunocompromised, clinical_trial]):
            return False
        return True

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Eczema protocol satisfied.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Eczema protocol not satisfied.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='eczema_diagnosis',
                    condition=TobaccoUseScreening,
                    title='Confirm Eczema Diagnosis',
                    narrative='Confirm diagnosis of eczema and document severity.',
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='eczema_education',
                    instruction=BehavioralHealthFollowUpVisit,
                    title='Provide Eczema Education',
                    narrative='Educate caregivers on eczema management and treatment.',
                    patient=self.patient
                ))
                result.add_recommendation(PlanRecommendation(
                    key='eczema_follow_up',
                    title='Schedule Eczema Follow-Up',
                    narrative='Plan follow-up visits to monitor eczema treatment outcomes.',
                    patient=self.patient
                ))
        return result