import arrow
from canvas_workflow_kit.patient import Patient
from canvas_workflow_kit.patient_recordset import PatientEventRecordSet
from canvas_workflow_kit.protocol import ClinicalQualityMeasure, ProtocolResult, STATUS_DUE, STATUS_SATISFIED
from canvas_workflow_kit.recommendation import InterviewRecommendation, InstructionRecommendation, FollowUpRecommendation
from canvas_workflow_kit.value_set import ValueSet
from canvas_workflow_kit.value_set.v2021.encounter_performed import OfficeVisit, OutpatientConsultation, HospitalInpatientVisitInitial, ContactOrOfficeVisit
class RoutineVisitValueSet(ValueSet): pass
class LifeThreateningConditionValueSet(ValueSet): pass
class CommunicationIssueValueSet(ValueSet): pass
class SOAPOptOutValueSet(ValueSet): pass
class SOAPNoteProtocol(ClinicalQualityMeasure):
    def in_initial_population(self) -> bool:
        return len(self.patient.reason_for_visits.find(RoutineVisitValueSet)) > 0
    def in_denominator(self) -> bool:
        exclusions = self.patient.conditions.find(LifeThreateningConditionValueSet) + \
                     self.patient.conditions.find(CommunicationIssueValueSet) + \
                     self.patient.inpatient_stays.find(HospitalInpatientVisitInitial) + \
                     self.patient.interviews.find(SOAPOptOutValueSet)
        return len(exclusions) == 0
    def in_numerator(self) -> bool:
        soap_note = self.patient.interviews.find(OfficeVisit)
        return len(soap_note) > 0
    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        result.status = STATUS_SATISFIED if self.in_numerator() else STATUS_DUE
        result.add_narrative('Complete SOAP note for comprehensive evaluation.')
        if not self.in_numerator():
            result.add_recommendation(InterviewRecommendation(
                key='subjective',
                interview=OfficeVisit,
                title='Complete Subjective Section',
                narrative='Gather patient history and complaints.',
                patient=self.patient
            ))
            result.add_recommendation(InterviewRecommendation(
                key='objective',
                interview=OfficeVisit,
                title='Complete Objective Section',
                narrative='Conduct physical examination and diagnostic tests.',
                patient=self.patient
            ))
            result.add_recommendation(InterviewRecommendation(
                key='assessment',
                interview=OfficeVisit,
                title='Complete Assessment Section',
                narrative='Formulate differential diagnosis.',
                patient=self.patient
            ))
            result.add_recommendation(InterviewRecommendation(
                key='plan',
                interview=OutpatientConsultation,
                title='Complete Plan Section',
                narrative='Develop management plan.',
                patient=self.patient
            ))
            result.add_recommendation(InstructionRecommendation(
                key='inform',
                instruction='Inform Patient',
                title='Inform Patient of Diagnosis and Plan',
                narrative='Ensure patient understands diagnosis and management plan.',
                patient=self.patient
            ))
            result.add_recommendation(FollowUpRecommendation(
                key='follow_up',
                title='Schedule Follow-Up',
                narrative='Arrange follow-up appointments or referrals as needed.',
                patient=self.patient
            ))
        return result