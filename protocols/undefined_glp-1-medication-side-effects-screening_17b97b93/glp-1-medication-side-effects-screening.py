import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientPeriodRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import (
    AllergyRecommendation,
    InterviewRecommendation,
    LabRecommendation
)
from canvas_workflow_kit.value_set.v2021.encounter import EncounterInpatient
from canvas_workflow_kit.value_set.v2020 import AnnualWellnessVisit
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesEstablishedOfficeVisit18AndUp, OfficeVisit

class GLP1MedicationValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1SideEffectScreening(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Medication Side Effect Screening'

    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1MedicationValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1MedicationValueSet)
        four_weeks_ago = arrow.now().shift(weeks=-4)
        recent_screenings = self.patient.interviews.find(AnnualWellnessVisit | PreventiveCareServicesEstablishedOfficeVisit18AndUp).after(arrow.now().shift(months=-3))
        return len(glp1_prescriptions) > 0 and len(recent_screenings) == 0

    def in_numerator(self) -> bool:
        glp1_allergies = self.patient.allergy_intolerances.find(GLP1AllergyValueSet)
        hospitalized = len(self.patient.inpatient_stays.find(EncounterInpatient).after(arrow.now().shift(weeks=-4))) > 0
        discontinued = len(self.patient.medications.find(GLP1MedicationValueSet).before(arrow.now().shift(weeks=-4))) > 0
        return len(glp1_allergies) == 0 and not hospitalized and not discontinued

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('GLP-1 medication side effect screening completed successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('GLP-1 medication side effect screening is due.')
                result.add_recommendation(AllergyRecommendation(
                    key='glp1_allergy_check',
                    title='Check for GLP-1 Allergies',
                    allergy=GLP1AllergyValueSet,
                    narrative='Verify no allergies to GLP-1 medications.'
                ))
                result.add_recommendation(InterviewRecommendation(
                    key='glp1_side_effect_screening',
                    title='Conduct GLP-1 Side Effect Screening',
                    questionnaires=[AnnualWellnessVisit, PreventiveCareServicesEstablishedOfficeVisit18AndUp],
                    narrative='Conduct a comprehensive review of GLP-1 medication side effects.'
                ))
                result.add_recommendation(LabRecommendation(
                    key='glp1_lab_tests',
                    title='Order Lab Tests for GLP-1 Side Effects',
                    lab=GLP1MedicationValueSet,
                    condition=None,
                    narrative='Order lab tests to evaluate potential GLP-1 medication side effects.',
                    patient=self.patient
                ))
        return result