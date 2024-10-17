import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import AssessRecommendation, InstructionRecommendation

class ConcussionValueSet(ValueSet):
    pass

class ConcussionProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        return len(concussion_diagnosis) > 0

    def in_denominator(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        rest_period = self.patient.instructions.find(ConcussionValueSet)
        return len(concussion_diagnosis) > 0 and len(rest_period) > 0

    def in_numerator(self) -> bool:
        baseline_assess = self.patient.assessments.find(ConcussionValueSet)
        post_injury_eval = self.patient.assessments.find(ConcussionValueSet)
        final_clearance = self.patient.instructions.find(ConcussionValueSet)
        return len(baseline_assess) > 0 and len(post_injury_eval) > 0 and len(final_clearance) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE

        if not self.in_numerator():
            baseline_recommendation = AssessRecommendation(
                key='baseline_assess',
                title='Perform Baseline Assessment',
                context={'narrative': 'Conduct baseline cognitive and physical assessments to establish pre-injury status.'},
                patient=self.patient
            )
            post_injury_recommendation = AssessRecommendation(
                key='post_injury_eval',
                title='Conduct Post-Injury Evaluation',
                context={'narrative': 'Perform post-injury cognitive and physical evaluations to assess recovery.'},
                patient=self.patient
            )
            clearance_recommendation = InstructionRecommendation(
                key='final_clearance',
                instruction='Provide final clearance for return to play.',
                title='Final Clearance',
                context={'narrative': 'Ensure symptom-free status and return to baseline function before clearing for play.'},
                patient=self.patient
            )
            result.add_recommendation(baseline_recommendation)
            result.add_recommendation(post_injury_recommendation)
            result.add_recommendation(clearance_recommendation)

        return result