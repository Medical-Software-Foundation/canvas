import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet, PatientPeriodRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.diagnosis import Concussion, NeurologicalDisorder
from canvas_workflow_kit.value_set.v2021.procedure import RestPeriod
from canvas_workflow_kit.recommendation import InstructionRecommendation, PerformRecommendation

class ReturnToPlayProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        concussion_diagnosis = self.patient.conditions.find(Concussion)
        return len(concussion_diagnosis) > 0

    def in_denominator(self) -> bool:
        concussion_evaluation = self.patient.procedures.find(Concussion)
        sports_concussion = self.patient.conditions.find(Concussion)
        pre_existing_conditions = self.patient.conditions.find(NeurologicalDisorder)
        rest_period = self.patient.procedures.find(RestPeriod)
        return (
            len(concussion_evaluation) > 0 and
            len(sports_concussion) > 0 and
            len(pre_existing_conditions) == 0 and
            len(rest_period) > 0
        )

    def in_numerator(self) -> bool:
        return_to_play = self.patient.procedures.find(RestPeriod)
        return len(return_to_play) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE

        if not self.in_numerator():
            result.add_narrative('The patient has not completed the return-to-play protocol.')
            result.add_recommendation(InstructionRecommendation(
                key='initial_rest',
                instruction='Ensure a period of physical and cognitive rest immediately following the concussion.',
                title='Initial Rest',
                narrative='Recommend a period of rest as per healthcare provider’s advice.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='gradual_return',
                instruction='Follow a stepwise return-to-play protocol with stages of increasing physical activity.',
                title='Gradual Return-to-Play',
                narrative='Recommend a gradual return to physical activity.',
                patient=self.patient
            ))
            result.add_recommendation(PerformRecommendation(
                key='medical_clearance',
                procedure=Concussion,
                title='Obtain Medical Clearance',
                narrative='Recommend obtaining written clearance from a healthcare professional.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='education_documentation',
                instruction='Educate the athlete and document each stage of the return-to-play process.',
                title='Education and Documentation',
                narrative='Provide education and document the return-to-play process.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='post_return_monitoring',
                instruction='Continue to monitor the athlete for any recurrence of symptoms after returning to play.',
                title='Post-Return Monitoring',
                narrative='Recommend monitoring for any recurrence of symptoms.',
                patient=self.patient
            ))

        return result