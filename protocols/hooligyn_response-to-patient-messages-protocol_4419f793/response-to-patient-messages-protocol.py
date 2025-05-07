import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import InstructionRecommendation

class PatientMessageValueSet(ValueSet):
    pass

class CanvasPatientPortalProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True

    def in_denominator(self) -> bool:
        return True

    def in_numerator(self) -> bool:
        return True

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED

        instruction = InstructionRecommendation(
            key='canvas_portal',
            instruction='Log into the Canvas Patient Portal at the beginning of each shift to check for new patient messages. Ensure that all patient messages are acknowledged within 24 hours of receipt.',
            title='Canvas Patient Portal Instructions',
            narrative='Log into the Canvas Patient Portal at the beginning of each shift to check for new patient messages. Ensure that all patient messages are acknowledged within 24 hours of receipt.'
        )
        result.add_recommendation(instruction)

        return result