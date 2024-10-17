import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import InterviewRecommendation, LabRecommendation, AllergyRecommendation, PrescribeRecommendation, ReferRecommendation

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1SideEffectsProtocol(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Side Effects Screening'

    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_4_weeks_ago = arrow.now().shift(weeks=-4)
        glp1_duration = self.patient.prescriptions.find(GLP1ValueSet).before(start_4_weeks_ago)
        no_recent_screen = len(self.patient.interviews.find(GLP1ValueSet).after(arrow.now().shift(months=-3))) == 0
        return len(glp1_duration) > 0 and no_recent_screen

    def in_numerator(self) -> bool:
        no_allergy = len(self.patient.allergy_intolerances.find(GLP1AllergyValueSet)) == 0
        not_discontinued = len(self.patient.medications.find(GLP1ValueSet).after(arrow.now().shift(weeks=-4))) > 0
        not_hospitalized = len(self.patient.inpatient_stays.after(arrow.now().shift(weeks=-4))) == 0
        not_palliative = len(self.patient.conditions.find(ValueSet).after(arrow.now().shift(weeks=-4))) == 0
        return no_allergy and not_discontinued and not_hospitalized and not_palliative

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('GLP-1 side effects screening completed successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('GLP-1 side effects screening is due.')
                result.add_recommendation(AllergyRecommendation(
                    key='check_allergy',
                    title='Check for GLP-1 Allergy',
                    allergy=GLP1AllergyValueSet,
                    narrative='Verify if the patient has any documented allergy to GLP-1 medications.'
                ))
                result.add_recommendation(PrescribeRecommendation(
                    key='continue_glp1',
                    prescription=GLP1ValueSet,
                    title='Continue GLP-1 Medication',
                    narrative='Ensure the patient continues GLP-1 medication if no issues are found.'
                ))
                result.add_recommendation(ReferRecommendation(
                    key='hospitalization_check',
                    referral=ValueSet,
                    title='Check Hospitalization Status',
                    narrative='Verify if the patient is currently hospitalized.'
                ))
                result.add_recommendation(ReferRecommendation(
                    key='palliative_check',
                    referral=ValueSet,
                    title='Check Palliative Care Status',
                    narrative='Verify if the patient is under palliative care.'
                ))
        return result