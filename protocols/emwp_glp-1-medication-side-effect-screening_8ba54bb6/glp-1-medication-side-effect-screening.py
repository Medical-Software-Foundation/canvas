import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import InterviewRecommendation, LabRecommendation, FollowUpRecommendation
from canvas_workflow_kit.value_set.v2020 import MedicalReason
from canvas_workflow_kit.value_set.v2021.encounter import EncounterInpatient
from canvas_workflow_kit.value_set.v2020 import ContactOrOfficeVisit
from canvas_workflow_kit.value_set.v2021.encounter import EncounterToScreenForBloodPressure
from canvas_workflow_kit.value_set.v2021.encounter_performed import PreventiveCareServicesEstablishedOfficeVisit18AndUp
from canvas_workflow_kit.value_set.v2021.diagnosis import Cancer
from canvas_workflow_kit.value_set.v2020 import Cancer as Cancer2020
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(MedicalReason):
    pass

class GLP1SideEffectsQuestionnaireValueSet(ValueSet):
    pass

class GLP1SideEffectsMeasure(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Medication Side Effects Screening'

    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_date = arrow.now().shift(weeks=-4)
        recent_glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet).after(start_date)
        no_recent_screen = len(self.patient.interviews.find(GLP1SideEffectsQuestionnaireValueSet).after(arrow.now().shift(months=-3))) == 0
        return len(recent_glp1_prescriptions) > 0 and no_recent_screen

    def in_numerator(self) -> bool:
        no_allergy = len(self.patient.allergy_intolerances.find(GLP1AllergyValueSet)) == 0
        not_discontinued = len(self.patient.medications.find(GLP1ValueSet).before(arrow.now().shift(weeks=-4))) == 0
        not_hospitalized = len(self.patient.inpatient_stays.find(EncounterInpatient).after(arrow.now().shift(weeks=-4))) == 0
        return no_allergy and not_discontinued and not_hospitalized

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_initial_population() and self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_DUE
                result.add_narrative('Conduct a comprehensive review of the patient’s medical history and current symptoms.')
                result.add_narrative('Administer a standardized questionnaire to assess common side effects associated with GLP-1 medications.')
                result.add_narrative('Perform necessary laboratory tests if indicated by the questionnaire responses.')
                result.add_recommendation(InterviewRecommendation(
                    key='glp1_side_effects_questionnaire',
                    title='Administer GLP-1 Side Effects Questionnaire',
                    context={'narrative': 'Administer a standardized questionnaire to assess common side effects associated with GLP-1 medications.'},
                    patient=self.patient
                ))
                result.add_recommendation(LabRecommendation(
                    key='glp1_lab_tests',
                    title='Order Lab Tests',
                    context={'narrative': 'Perform necessary laboratory tests if indicated by the questionnaire responses.'},
                    patient=self.patient
                ))
                result.add_recommendation(FollowUpRecommendation(
                    key='glp1_follow_up',
                    title='Schedule Follow-Up',
                    context={'narrative': 'Recommend a follow-up consultation with a healthcare provider if significant side effects are identified.'},
                    patient=self.patient
                ))
            else:
                result.status = STATUS_SATISFIED
                result.add_narrative('No further action required. Patient is not eligible for GLP-1 side effects screening.')
        else:
            result.status = STATUS_NOT_APPLICABLE
        return result