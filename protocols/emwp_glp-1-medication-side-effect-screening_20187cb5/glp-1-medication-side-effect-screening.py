import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientPeriodRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.procedure import LaboratoryTestsForHypertension
from canvas_workflow_kit.value_set.v2021.encounter_performed import OutpatientConsultation
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import AllergyRecommendation, PrescribeRecommendation, PlanRecommendation, LabRecommendation, ReferRecommendation

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1TrialValueSet(ValueSet):
    pass

class GLP1SideEffectScreening(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Side Effect Screening'

    def in_initial_population(self) -> bool:
        glp1_meds = self.patient.medications.find(GLP1ValueSet)
        return len(glp1_meds) > 0

    def in_denominator(self) -> bool:
        four_weeks_ago = arrow.now().shift(weeks=-4)
        three_months_ago = arrow.now().shift(months=-3)
        glp1_meds = self.patient.medications.find(GLP1ValueSet).intersects(four_weeks_ago, still_active=True)
        recent_screen = self.patient.interviews.find(GLP1ValueSet).after(three_months_ago)
        return len(glp1_meds) > 0 and len(recent_screen) == 0

    def in_numerator(self) -> bool:
        four_weeks_ago = arrow.now().shift(weeks=-4)
        glp1_allergy = self.patient.allergy_intolerances.find(GLP1AllergyValueSet)
        discontinued_meds = self.patient.medications.find(GLP1ValueSet).intersects(four_weeks_ago, still_active=False)
        in_trial = self.patient.procedures.find(GLP1TrialValueSet).after(arrow.now().shift(weeks=-4))
        terminal_illness = self.patient.conditions.find(GLP1ValueSet).after(arrow.now().shift(weeks=-4))
        return len(glp1_allergy) == 0 and len(discontinued_meds) == 0 and len(in_trial) == 0 and len(terminal_illness) == 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('GLP-1 side effect screening completed successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('GLP-1 side effect screening is due.')
                result.add_recommendation(AllergyRecommendation(
                    key='glp1_allergy',
                    title='Check for GLP-1 Allergy',
                    narrative='Evaluate for any known allergy or hypersensitivity to GLP-1 medications.',
                    allergy=GLP1AllergyValueSet
                ))
                result.add_recommendation(PrescribeRecommendation(
                    key='glp1_prescribe',
                    title='Continue GLP-1 Prescription',
                    narrative='Ensure GLP-1 medications are not discontinued.',
                    prescription=GLP1ValueSet
                ))
                result.add_recommendation(PlanRecommendation(
                    key='glp1_trial',
                    title='Review Clinical Trial Participation',
                    narrative='Verify patient is not in a trial monitoring GLP-1 side effects.',
                    patient=self.patient
                ))
                result.add_recommendation(LabRecommendation(
                    key='renal_liver_tests',
                    title='Order Renal and Liver Function Tests',
                    narrative='Perform renal and liver function tests to monitor potential side effects.',
                    lab=LaboratoryTestsForHypertension,
                    condition=GLP1ValueSet,
                    patient=self.patient
                ))
                result.add_recommendation(ReferRecommendation(
                    key='consultation',
                    title='Consultation with Healthcare Provider',
                    narrative='Recommend consultation if significant side effects are identified.',
                    referral=OutpatientConsultation,
                    condition=GLP1ValueSet,
                    patient=self.patient
                ))
        return result