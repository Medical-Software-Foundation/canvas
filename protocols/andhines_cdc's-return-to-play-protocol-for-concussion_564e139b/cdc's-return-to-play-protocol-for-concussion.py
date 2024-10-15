import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import AssessRecommendation, PerformRecommendation, InstructionRecommendation
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import LiverDisease, MentalHealthDiagnoses
from canvas_workflow_kit.value_set.v2021.lab_test import ChlamydiaScreening

class ConcussionValueSet(LiverDisease):
    pass

class CognitiveTestValueSet(ValueSet):
    pass

class BalanceTestValueSet(ChlamydiaScreening):
    pass

class ReturnToPlayProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        return len(concussion_diagnosis) > 0

    def in_denominator(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(ConcussionValueSet)
        post_acute_phase = arrow.now().shift(days=-1)
        initial_evaluation = self.patient.procedures.find(CognitiveTestValueSet)
        return (len(concussion_diagnosis) > 0 and
                self.patient.age_at(post_acute_phase) > 0 and
                len(initial_evaluation) > 0)

    def in_numerator(self) -> bool:
        severe_symptoms = self.patient.conditions.find(ConcussionValueSet).after(arrow.now().shift(days=-1))
        multiple_concussions = len(self.patient.conditions.find(ConcussionValueSet)) > 1
        coexisting_conditions = len(self.patient.conditions.find(MentalHealthDiagnoses)) > 0
        lack_of_follow_up = len(self.patient.procedures.find(ValueSet)) == 0
        if (len(severe_symptoms) > 0 or
            multiple_concussions or
            coexisting_conditions or
            lack_of_follow_up):
            return False

        cognitive_test = self.patient.procedures.find(CognitiveTestValueSet)
        balance_test = self.patient.procedures.find(BalanceTestValueSet)
        no_symptoms = len(self.patient.conditions.find(ConcussionValueSet).after(arrow.now().shift(days=-1))) == 0
        completed_protocol = len(cognitive_test) > 0 and len(balance_test) > 0 and no_symptoms
        return completed_protocol

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_NOT_APPLICABLE

        if not (self.in_initial_population() and self.in_denominator()):
            return result

        result.status = STATUS_DUE
        result.add_narrative('Patient is in the post-acute phase of concussion recovery.')

        severe_symptoms = self.patient.conditions.find(ConcussionValueSet).after(arrow.now().shift(days=-1))
        if len(severe_symptoms) > 0:
            result.add_recommendation(AssessRecommendation(
                key='severe_symptoms',
                title='Assess Severe Symptoms',
                context={'narrative': 'Evaluate and manage severe or worsening neurological symptoms.'}
            ))

        multiple_concussions = len(self.patient.conditions.find(ConcussionValueSet)) > 1
        if multiple_concussions:
            result.add_recommendation(InstructionRecommendation(
                key='multiple_concussions',
                title='Provide Guidance on Multiple Concussions',
                context={'narrative': 'Advise on risks and management of multiple concussions.'}
            ))

        coexisting_conditions = len(self.patient.conditions.find(MentalHealthDiagnoses)) > 0
        if coexisting_conditions:
            result.add_recommendation(InstructionRecommendation(
                key='coexisting_conditions',
                title='Manage Co-existing Conditions',
                context={'narrative': 'Address co-existing medical conditions complicating recovery.'}
            ))

        lack_of_follow_up = len(self.patient.procedures.find(ValueSet)) == 0
        if lack_of_follow_up:
            result.add_recommendation(InstructionRecommendation(
                key='follow_up',
                title='Ensure Medical Follow-Up',
                context={'narrative': 'Arrange appropriate medical follow-up during return-to-play process.'}
            ))

        cognitive_test = self.patient.procedures.find(CognitiveTestValueSet)
        if len(cognitive_test) == 0:
            result.add_recommendation(PerformRecommendation(
                key='cognitive_test',
                title='Perform Cognitive Test',
                context={'narrative': 'Conduct cognitive testing to assess return to baseline function.'}
            ))

        balance_test = self.patient.procedures.find(BalanceTestValueSet)
        if len(balance_test) == 0:
            result.add_recommendation(PerformRecommendation(
                key='balance_test',
                title='Perform Balance Test',
                context={'narrative': 'Conduct balance testing to ensure normal coordination.'}
            ))

        no_symptoms = len(self.patient.conditions.find(ConcussionValueSet).after(arrow.now().shift(days=-1))) == 0
        if not no_symptoms:
            result.add_recommendation(InstructionRecommendation(
                key='symptom_management',
                title='Manage Concussion Symptoms',
                context={'narrative': 'Provide guidance on managing and monitoring concussion symptoms.'}
            ))

        if self.in_numerator():
            result.status = STATUS_SATISFIED
            result.add_narrative('Patient has successfully completed the return-to-play protocol.')

        return result