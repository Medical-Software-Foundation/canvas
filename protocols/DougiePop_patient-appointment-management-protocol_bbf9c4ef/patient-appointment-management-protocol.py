import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.protocol import STATUS_NOT_APPLICABLE
from canvas_workflow_kit.recommendation import TaskRecommendation
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2022 import OfficeVisit, OutpatientConsultation
from canvas_workflow_kit.value_set.v2022 import FollowUpWithin4Weeks, BehavioralHealthFollowUpVisit
from canvas_workflow_kit.value_set.v2022 import ContactOrOfficeVisit
class AppointmentSchedulingMeasure(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return True
    def in_denominator(self) -> bool:
        return True
    def in_numerator(self) -> bool:
        return True
    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if (self.in_numerator() and self.in_denominator()) else STATUS_DUE
        if not (self.in_numerator() and self.in_denominator()):
            result.status = STATUS_NOT_APPLICABLE
        if self.in_denominator() and not self.in_numerator():
            result.status = STATUS_DUE
            result.add_recommendation(TaskRecommendation(
                key='inactive_deceased_check',
                title='Check Inactive or Deceased Status',
                narrative='Verify if the patient is marked as inactive or deceased in the EHR system.',
                patient=self.patient
            ))
            result.add_recommendation(TaskRecommendation(
                key='opt_out_check',
                title='Check Opt-Out Status',
                narrative='Verify if the patient has opted out of receiving appointment scheduling services.',
                patient=self.patient
            ))
            result.add_recommendation(TaskRecommendation(
                key='outstanding_balance_check',
                title='Check Outstanding Balance',
                narrative='Verify if the patient has an outstanding balance exceeding the threshold.',
                patient=self.patient
            ))
            result.add_recommendation(TaskRecommendation(
                key='non_compliance_check',
                title='Check Non-Compliance',
                narrative='Verify if the patient has been flagged for non-compliance with previous appointments.',
                patient=self.patient
            ))
        return result