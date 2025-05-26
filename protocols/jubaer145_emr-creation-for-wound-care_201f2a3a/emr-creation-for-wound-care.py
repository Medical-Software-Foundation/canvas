import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED, STATUS_NOT_APPLICABLE
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import (
    InstructionRecommendation,
    PlanRecommendation,
    FollowUpRecommendation
)
from canvas_workflow_kit.value_set.v2022 import (
    OpenWoundOfEyeball,
    PreventiveCareServicesIndividualCounseling,
    OutpatientConsultation,
    AntiInfectives_Other,
    StandardizedPainAssessmentTool,
    DtapVaccine
)

class WoundCareProtocol(ClinicalQualityMeasure):
    class WoundCareValueSet(OpenWoundOfEyeball):
        pass

    class WoundAssessmentValueSet(PreventiveCareServicesIndividualCounseling):
        pass

    class TreatmentPlanValueSet(OutpatientConsultation):
        pass

    def in_initial_population(self) -> bool:
        return len(self.patient.reason_for_visits.find(self.WoundCareValueSet)) > 0

    def in_denominator(self) -> bool:
        return (
            len(self.patient.procedures.find(self.WoundCareValueSet)) > 0 and
            len(self.patient.procedures.find(self.WoundAssessmentValueSet)) > 0
        )

    def in_numerator(self) -> bool:
        return (
            len(self.patient.instructions.find(self.WoundCareValueSet)) > 0 and
            len(self.patient.plans.find(self.TreatmentPlanValueSet)) > 0 and
            len(self.patient.follow_ups.find(self.WoundCareValueSet)) > 0
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if not (self.in_initial_population() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        else:
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Wound care protocol completed successfully.')
            else:
                result.status = STATUS_DUE
                result.add_narrative('Wound care protocol is due.')
                result.add_recommendation(InstructionRecommendation(
                    key='wound_care_instructions',
                    instruction='Provide wound care instructions to the patient.',
                    title='Wound Care Instructions',
                    narrative='Document wound care instructions given to the patient.',
                    patient=self.patient
                ))
                result.add_recommendation(PlanRecommendation(
                    key='wound_treatment_plan',
                    plan='Document the treatment plan for the wound.',
                    title='Wound Treatment Plan',
                    narrative='Record the treatment plan for ongoing wound care.',
                    patient=self.patient
                ))
                result.add_recommendation(FollowUpRecommendation(
                    key='wound_follow_up',
                    title='Wound Care Follow-up',
                    narrative='Schedule a follow-up appointment for wound care.',
                    patient=self.patient
                ))
        return result