import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import AllergyRecommendation, LabRecommendation, InstructionRecommendation
from canvas_workflow_kit.value_set.v2021.encounter import EncounterInpatient
from canvas_workflow_kit.value_set.v2021.encounter_performed import OutpatientConsultation, OfficeVisit

class GLP1ValueSet(ValueSet):
    pass

class GLP1AllergyValueSet(ValueSet):
    pass

class GLP1SideEffectsMeasure(ClinicalQualityMeasure):
    class Meta:
        title = 'GLP-1 Side Effects Screening'

    def in_initial_population(self) -> bool:
        glp1_prescriptions = self.patient.prescriptions.find(GLP1ValueSet)
        return len(glp1_prescriptions) > 0

    def in_denominator(self) -> bool:
        start_date = arrow.now().shift(weeks=-4)
        recent_glp1 = self.patient.medications.find(GLP1ValueSet).intersect(start_date, arrow.now())
        last_screening = self.patient.interviews.find(GLP1ValueSet).after(arrow.now().shift(months=-3))
        return len(recent_glp1) > 0 and len(last_screening) == 0

    def in_numerator(self) -> bool:
        no_allergy = len(self.patient.allergy_intolerances.find(GLP1AllergyValueSet)) == 0
        not_hospitalized = len(self.patient.inpatient_stays.find(EncounterInpatient).after(arrow.now().shift(weeks=-2))) == 0
        not_discontinued = len(self.patient.medications.find(GLP1ValueSet).intersect(arrow.now().shift(weeks=-2), arrow.now())) > 0
        return no_allergy and not_hospitalized and not_discontinued

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
                    key='glp1_allergy_check',
                    title='Check for GLP-1 Allergies',
                    allergy=GLP1AllergyValueSet,
                    narrative='Verify no allergies to GLP-1 medications.'
                ))
                result.add_recommendation(LabRecommendation(
                    key='pancreatitis_lab',
                    title='Order Pancreatitis Labs',
                    lab=GLP1ValueSet,
                    condition=None,
                    narrative='Order serum amylase and lipase to rule out pancreatitis.'
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='glp1_side_effects_instruction',
                    title='Provide GLP-1 Side Effects Instructions',
                    instructions='Educate patient on potential GLP-1 side effects and when to seek help.',
                    narrative='Provide instructions on GLP-1 side effects.'
                ))
        return result