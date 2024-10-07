import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientPeriodRecordSet, PatientEventRecordSet
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.encounter import EncounterInpatient
from canvas_workflow_kit.value_set.v2021.diagnosis import Cancer as Cancer2021
from canvas_workflow_kit.value_set.v2020 import Cancer as Cancer2020
from canvas_workflow_kit.value_set.v2021.encounter_performed import OutpatientConsultation
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import InterviewRecommendation, LabRecommendation, ReferRecommendation

class GLP1ReceptorAgonists(ValueSet):
    pass

class GLP1Allergies(ValueSet):
    pass

class GLP1SideEffectsQuestionnaire(ValueSet):
    pass

class PancreatitisLabTest(ValueSet):
    pass

class GLP1MedicationProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        glp1_medications = self.patient.medications.find(GLP1ReceptorAgonists)
        return len(glp1_medications) > 0

    def in_denominator(self) -> bool:
        four_weeks_ago = arrow.now().shift(weeks=-4)
        three_months_ago = arrow.now().shift(months=-3)
        glp1_medications = self.patient.medications.find(GLP1ReceptorAgonists)
        long_term_use = len(glp1_medications.intersects(four_weeks_ago, now=True)) > 0
        no_recent_screening = len(self.patient.interviews.find(GLP1SideEffectsQuestionnaire).after(three_months_ago)) == 0
        return long_term_use and no_recent_screening

    def in_numerator(self) -> bool:
        no_allergies = len(self.patient.allergy_intolerances.find(GLP1Allergies)) == 0
        not_hospitalized = len(self.patient.inpatient_stays.find(EncounterInpatient).after(arrow.now().shift(weeks=-4))) == 0
        not_discontinued = len(self.patient.medications.find(GLP1ReceptorAgonists).before(arrow.now().shift(weeks=-4))) == 0
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
                if len(self.patient.allergy_intolerances.find(GLP1Allergies)) > 0:
                    result.add_recommendation(
                        InterviewRecommendation(
                            key='glp1_allergy_check',
                            questionnaires=[GLP1SideEffectsQuestionnaire],
                            title='Check for GLP-1 Allergies',
                            narrative='Conduct an interview to assess any allergies to GLP-1 medications.',
                            patient=self.patient
                        )
                    )
                if len(self.patient.inpatient_stays.find(EncounterInpatient).after(arrow.now().shift(weeks=-4))) > 0:
                    result.add_recommendation(
                        LabRecommendation(
                            key='pancreatitis_lab',
                            lab=PancreatitisLabTest,
                            condition=None,
                            title='Order Pancreatitis Lab Test',
                            narrative='Order serum amylase and lipase levels to evaluate for pancreatitis.',
                            patient=self.patient
                        )
                    )
                if len(self.patient.medications.find(GLP1ReceptorAgonists).before(arrow.now().shift(weeks=-4))) > 0:
                    result.add_recommendation(
                        InterviewRecommendation(
                            key='glp1_discontinuation',
                            questionnaires=[GLP1SideEffectsQuestionnaire],
                            title='Evaluate GLP-1 Discontinuation',
                            narrative='Assess the impact of discontinuing GLP-1 medications.',
                            patient=self.patient
                        )
                    )
        return result