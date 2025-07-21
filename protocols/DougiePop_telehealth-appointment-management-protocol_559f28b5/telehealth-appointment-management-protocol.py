import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.recommendation import FollowUpRecommendation
from canvas_workflow_kit.value_set.v2021 import TelephoneEvaluation, TelephoneManagement
from canvas_workflow_kit.value_set.v2022 import OnlineAssessments, TelehealthServices, TelephoneVisits
from canvas_workflow_kit.value_set.v2020 import OfficeVisit_1005
from canvas_workflow_kit.value_set.v2022 import OfficeVisit

TelehealthValueSet = TelephoneEvaluation | TelephoneManagement | OnlineAssessments | TelehealthServices | TelephoneVisits
NotTelehealthValueSet = OfficeVisit_1005 | OfficeVisit

class TelehealthProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return len(self.patient.reason_for_visits.find(TelehealthValueSet)) > 0

    def in_denominator(self) -> bool:
        telehealth_appointments = self.patient.reason_for_visits.find(TelehealthValueSet)
        return len(telehealth_appointments) > 0

    def in_numerator(self) -> bool:
        telehealth_appointments = self.patient.reason_for_visits.find(TelehealthValueSet)
        return len(telehealth_appointments) > 0

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_numerator():
            result.status = STATUS_SATISFIED
            result.add_narrative('Telehealth appointments are properly recorded.')
        else:
            result.status = STATUS_DUE
            result.add_narrative('Review telehealth appointments for accuracy.')
            result.add_recommendation(FollowUpRecommendation(
                key='not_telehealth',
                title='Verify Non-Telehealth Appointments',
                narrative='Ensure appointments not labeled as telehealth are correctly categorized.',
                patient=self.patient
            ))
            result.add_recommendation(FollowUpRecommendation(
                key='canceled_no_show',
                title='Review Canceled or No-Show Appointments',
                narrative='Check telehealth appointments for cancellations or no-shows.',
                patient=self.patient
            ))
            result.add_recommendation(FollowUpRecommendation(
                key='duplicates_erroneous',
                title='Check for Duplicates or Erroneous Entries',
                narrative='Ensure no duplicate or erroneous telehealth appointments exist.',
                patient=self.patient
            ))
        return result