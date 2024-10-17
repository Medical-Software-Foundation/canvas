import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import InterviewRecommendation, AllergyRecommendation, FollowUpRecommendation
from canvas_workflow_kit.value_set.v2021.encounter import EncounterInpatient
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit

class GLP1MedicationValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1SideEffectsQuestionnaire(ValueSet):
    pass

class GLP1SideEffectsMeasure(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Medication Side Effects Screening'

    def in_initial_population(self) -> bool:
        glp1_medications = self.patient.medications.find(GLP1MedicationValueSet)
        return len(glp1_medications) > 0

    def in_denominator(self) -> bool:
        start_date = arrow.now().shift(weeks=-4)
        recent_screen_timeframe = arrow.now().shift(months=-3)
        glp1_medications = self.patient.medications.find(GLP1MedicationValueSet)
        long_term_use = len(glp1_medications) > 0 and glp1_medications.intersects(start_date, arrow.now())
        no_recent_screen = len(self.patient.interviews.find(GLP1SideEffectsQuestionnaire).after(recent_screen_timeframe)) == 0
        return long_term_use and no_recent_screen

    def in_numerator(self) -> bool:
        no_allergies = len(self.patient.allergy_intolerances.find(GLP1AllergyValueSet)) == 0
        not_hospitalized = len(self.patient.inpatient_stays.find(EncounterInpatient).after(arrow.now().shift(weeks=-4))) == 0
        not_discontinued = len(self.patient.medications.find(GLP1MedicationValueSet).before(arrow.now().shift(weeks=-4))) == 0
        return no_allergies and not_hospitalized and not_discontinued

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('GLP-1 medication side effects screening completed successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('GLP-1 medication side effects screening is due.')
                interview_recommendation = InterviewRecommendation(
                    key='glp1_side_effects',
                    questionnaire=GLP1SideEffectsQuestionnaire,
                    title='Conduct GLP-1 Side Effects Questionnaire',
                    narrative='Administer a standardized questionnaire to assess common side effects associated with GLP-1 medications.',
                    patient=self.patient
                )
                allergy_recommendation = AllergyRecommendation(
                    key='glp1_allergy_check',
                    title='Check for GLP-1 Allergies',
                    narrative='Ensure no documented allergies or contraindications to GLP-1 medications.',
                    patient=self.patient
                )
                follow_up_recommendation = FollowUpRecommendation(
                    key='glp1_follow_up',
                    title='Schedule Follow-Up for GLP-1 Side Effects',
                    narrative='Recommend a follow-up consultation if significant side effects are identified.',
                    patient=self.patient
                )
                result.add_recommendation(interview_recommendation)
                result.add_recommendation(allergy_recommendation)
                result.add_recommendation(follow_up_recommendation)
        return result