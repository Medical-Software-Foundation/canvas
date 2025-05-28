import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import AssessRecommendation, DiagnoseRecommendation, InstructionRecommendation, InterviewRecommendation
from canvas_workflow_kit.value_set.v2022 import DementiaAndMentalDegenerations, SchizophreniaOrPsychoticDisorder
from canvas_workflow_kit.value_set.v2022 import StandardizedToolsForAssessmentOfCognition
from canvas_workflow_kit.value_set.v2022 import NystagmusAndOtherIrregularEyeMovements, InjuryToOpticNerveAndPathways, OtherDisordersOfOpticNerve

class MCIValueSet(ValueSet):
    pass

class CognitiveInterventionStudyValueSet(ValueSet):
    pass

class MCIProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return bool(
            self.patient.age_at(arrow.now()) >= 55 and
            len(self.patient.conditions.find(MCIValueSet)) > 0
        )

    def in_denominator(self) -> bool:
        return bool(
            self.in_initial_population() and
            len(self.patient.conditions.find(MCIValueSet)) > 0 and
            self.patient.age_at(arrow.now()) >= 55
        )

    def in_numerator(self) -> bool:
        return bool(
            self.in_denominator() and
            len(self.patient.conditions.find(DementiaAndMentalDegenerations)) == 0 and
            len(self.patient.conditions.find(SchizophreniaOrPsychoticDisorder)) == 0 and
            len(self.patient.conditions.find(NystagmusAndOtherIrregularEyeMovements)) == 0 and
            len(self.patient.conditions.find(CognitiveInterventionStudyValueSet)) == 0
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient meets all criteria for cognitive stimulation interventions.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Patient does not meet all criteria for cognitive stimulation interventions.')
                result.add_recommendation(DiagnoseRecommendation(
                    key='dementia_check',
                    condition=DementiaAndMentalDegenerations,
                    title='Evaluate for Dementia',
                    narrative='Recommend evaluating for dementia or Alzheimer’s disease.',
                    patient=self.patient
                ))
                result.add_recommendation(AssessRecommendation(
                    key='psychiatric_disorders',
                    title='Assess Psychiatric Disorders',
                    context={'narrative': 'Assess for severe psychiatric disorders that may interfere with cognitive interventions.'},
                    patient=self.patient
                ))
                result.add_recommendation(InstructionRecommendation(
                    key='sensory_impairments',
                    instruction='Evaluate and accommodate significant sensory impairments.',
                    title='Address Sensory Impairments',
                    narrative='Recommend addressing significant sensory impairments that cannot be accommodated.',
                    patient=self.patient
                ))
                result.add_recommendation(InterviewRecommendation(
                    key='study_participation',
                    interview=CognitiveInterventionStudyValueSet,
                    title='Check Study Participation',
                    narrative='Ensure patient is not currently participating in other cognitive intervention research studies.',
                    patient=self.patient
                ))
        return result