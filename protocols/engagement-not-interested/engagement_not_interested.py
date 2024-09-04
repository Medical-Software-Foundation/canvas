from enum import Enum
from typing import List

import arrow

from canvas_workflow_kit.patient_recordset import (
    BillingLineItemRecordSet,
    InterviewRecordSet,
    TaskRecordSet,
    UpcomingAppointmentRecordSet,
)
from canvas_workflow_kit.protocol import (
    CHANGE_TYPE,
    STATUS_DUE,
    STATUS_NOT_APPLICABLE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult,
)
from canvas_workflow_kit.value_set import ValueSet


PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID = 'QUES_PHONE_01'
ENGAGEMENT_TRANSITION_TASK_LABELS = ['Engagement', 'Transition']
DEFAULT_TIMEZONE = 'America/Phoenix'


class PhoneCallDispositionQuestionnaire(ValueSet):
    VALUE_SET_NAME = 'Phone Call Disposition Questionnaire'
    INTERNAL = {PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID}


class PhoneQuestions(Enum):
    DISPOSITION = 'QUES_PHONE_01'
    CALL_TO_FROM = 'QUES_PHONE_02'
    COMMENTS = 'QUES_PHONE_16'


class PhoneResponses(Enum):
    REACHED = 'QUES_PHONE_03'
    REACHED_NOT_INTERESTED = 'QUES_PHONE_04'
    NO_ANSWER_MESSAGE = 'QUES_PHONE_05'
    NO_ANSWER_NO_MESSAGE = 'QUES_PHONE_06'
    CALL_BACK_REQUESTED = 'QUES_PHONE_08'
    CALL_TO_PATIENT = 'QUES_PHONE_10'
    CALL_TO_OTHER = 'QUES_PHONE_11'
    FREE_TEXT = 'QUES_PHONE_16'


class AnnualAssessment(ValueSet):
    VALUE_SET_NAME = 'Annual Visit'
    CPT = {
        '99201',
        '99202',
        '99203',
        '99204',
        '99205',
        '99214',
        '99215',
        '99341',
        '99342',
        '99344',
        '99345',
        '99347',
        '99348',
        '99349',
        '99350',
        '99441',
        '99442',
        '99443',
    }


class NotInterested(ClinicalQualityMeasure):
    class Meta:
        title = 'New Member Engagement - Not Interested'
        description = ()
        version = '1.0.2'
        information = 'https://canvasmedical.com/gallery'
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [CHANGE_TYPE.INTERVIEW, CHANGE_TYPE.APPOINTMENT, CHANGE_TYPE.TASK]
        references: List[str] = []

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

    def _get_annual_assessments_after(self, start_time: arrow.Arrow) -> BillingLineItemRecordSet:
        '''Get annual assessments'''
        return self.patient.billing_line_items.find(AnnualAssessment).after(start_time)

    def _get_phone_calls_to_patient(self) -> InterviewRecordSet:
        '''Get all phone calls made to this patient.

        Returns:
            InterviewRecordSet: A set of phone call records made to the patient.
        '''
        phone_calls = self.patient.interviews.find(PhoneCallDispositionQuestionnaire).filter(
            status='AC'
        )
        return InterviewRecordSet(
            [
                phone_call
                for phone_call in phone_calls
                if any(
                    PhoneResponses(response['code']) == PhoneResponses.CALL_TO_PATIENT
                    for response in phone_call['responses']
                )
            ]
        )

    def _get_phone_call_responses(self) -> list[tuple[PhoneResponses, arrow.Arrow]]:
        '''Get all phone call responses for this patient, along with when they were received.'''
        return [
            (PhoneResponses(response['code']), arrow.get(phone_call['noteTimestamp']))
            for phone_call in self._get_phone_calls_to_patient().records
            for response in phone_call['responses']
        ]

    def _get_upcoming_appointments(self) -> UpcomingAppointmentRecordSet:
        '''Get all uncancelled upcoming appointments for this patient.'''
        return UpcomingAppointmentRecordSet(
            [
                appointment
                for appointment in self.patient.upcoming_appointments
                if appointment['status'] != 'cancelled'
            ]
        )

    def _get_tasks_by_label(self, labels: List[str]) -> TaskRecordSet:
        '''
        Get all tasks with specified labels.

        Parameters:
        labels (List[str]): The list of labels to filter tasks by.

        Returns:
        TaskRecordSet: A TaskRecordSet object containing the filtered tasks.
        '''
        open_tasks = self.patient.tasks.filter(
            status='OPEN',
        )
        return TaskRecordSet(
            [task for task in open_tasks if any(label in labels for label in task['labels'])]
        )

    def in_denominator_1(self) -> bool:
        '''
        Return True for patients who:
        * Have a 'non interested' status
        * Have not had an annual assessment this year
        * Do not have a engagement/transition task
        )
        '''
        return (
            not self._get_annual_assessments_after(arrow.get(self._now.year, 1, 1))
            and (
                PhoneResponses.REACHED_NOT_INTERESTED
                in (x[0] for x in self._get_phone_call_responses())
            )
            and not self._get_tasks_by_label(ENGAGEMENT_TRANSITION_TASK_LABELS)
        )

    def in_denominator_2(self) -> bool:
        '''
        Return True for patients who:
        * Have a 'non interested' status
        * Have had an annual assessment this year
        '''
        return (
            PhoneResponses.REACHED_NOT_INTERESTED
            in (x[0] for x in self._get_phone_call_responses())
        ) and bool(self._get_annual_assessments_after(arrow.get(self._now.year, 1, 1)))

    def in_numerator(self) -> bool:
        shift_days = -90 if self.in_denominator_1() else -30 if self.in_denominator_2() else 0
        return (
            any(x[1] > self._now.shift(days=shift_days) for x in self._get_phone_call_responses())
            if shift_days
            else False
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator_1() or self.in_denominator_2():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has indicated they are not interested recently.')
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative('Patient should be called to see if they are now interested.')
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Patient does not need to be called.')

        return result
