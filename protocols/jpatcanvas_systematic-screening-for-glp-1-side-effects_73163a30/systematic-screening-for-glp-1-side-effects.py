import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.encounter import EncounterInpatient
from canvas_workflow_kit.value_set.v2021.diagnosis import Cancer as Cancer2021
from canvas_workflow_kit.value_set.v2020 import Cancer as Cancer2020
from canvas_workflow_kit.recommendation import InterviewRecommendation, InstructionRecommendation, FollowUpRecommendation

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1Protocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        start_4_weeks_ago = arrow.now().shift(weeks=-4)
        recent_screenings = self.patient.interviews.find(GLP1ValueSet).after(start_4_weeks_ago)
        return len(glp1_prescriptions) > 0 and len(recent_screenings) == 0

    def in_numerator(self) -> bool:
        glp1_allergies = self.patient.allergy_intolerances.find(GLP1AllergyValueSet)
        inpatient_stays = self.patient.inpatient_stays.find(EncounterInpatient)
        thyroid_tumors = self.patient.conditions.find(Cancer2021 | Cancer2020)
        return len(glp1_allergies) == 0 and len(inpatient_stays) == 0 and len(thyroid_tumors) == 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('No contraindications or allergies to GLP-1 medications.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient should be screened for GLP-1 medication side effects.')
                result.add_recommendation(InterviewRecommendation(
                    key='glp1_side_effects',
                    interview=GLP1ValueSet,
                    title='Conduct GLP-1 Side Effects Interview',
                    narrative='Recommend conducting an interview to assess side effects of GLP-1 medications.',
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='glp1_education',
                    instruction=GLP1ValueSet,
                    title='Provide GLP-1 Medication Education',
                    narrative='Recommend providing education on potential side effects and management of GLP-1 medications.',
                    patient=self.patient
                ))
                result.add_recommendation(FollowUpRecommendation(
                    key='glp1_follow_up',
                    title='Schedule GLP-1 Follow-Up',
                    narrative='Recommend scheduling a follow-up to reassess GLP-1 medication side effects.',
                    patient=self.patient
                ))
        return result