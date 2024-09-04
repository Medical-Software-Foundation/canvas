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

DEFAULT_TIMEZONE = 'America/Phoenix'
# Replace this with the ID of your Phone Call Disposition Questionnaire
PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID = 'QUES_PHONE_01'

# Replace this with the labels of your engagement/transition tasks
ENGAGEMENT_TRANSITION_TASK_LABELS = ['Engagement', 'Transition']


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
    '''CPT codes for annual assessments.'''

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


class NewMembers(ClinicalQualityMeasure):
    class Meta:
        title = 'Engagement For New Members'
        description = (
            'This protocol identifies patients to be called who have not had an annual assessment, '
            'have had fewer than 5 phone call attempts, '
            'do not have an appointment scheduled, '
            'do not have a "non interested" status, '
            'and do not have a engagement/transition task.'
        )
        version = '1.0.2'
        information = (
            'https://canvasmedical.com/gallery'  # Replace this with a link to your protocol
        )
        identifiers: List[str]
        types = ['DUO']
        compute_on_change_types = [CHANGE_TYPE.INTERVIEW, CHANGE_TYPE.APPOINTMENT, CHANGE_TYPE.TASK]
        references: List[str]

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

    def _get_annual_assessments_between(
        self, start: arrow.Arrow, end: arrow.Arrow
    ) -> BillingLineItemRecordSet:
        '''
        Retrieves the annual assessments between the specified start and end dates.

        Args:
            start (arrow.Arrow): The start date of the range.
            end (arrow.Arrow): The end date of the range.

        Returns:
            BillingLineItemRecordSet: The billing line item record set containing the annual
                assessments in the given range.
        '''
        return self.patient.billing_line_items.find(AnnualAssessment).after(start).before(end)

    def _get_annual_assessments(self) -> BillingLineItemRecordSet:
        '''Get all annual assessments for this patient.

        Returns:
            BillingLineItemRecordSet: A record set containing all the annual assessments.
        '''
        return self.patient.billing_line_items.find(AnnualAssessment)

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

    def _get_phone_call_responses(self) -> List[PhoneResponses]:
        '''Get all phone call responses for this patient.

        Returns:
            A list of PhoneResponses objects representing the phone call responses.
        '''
        return [
            PhoneResponses(response['code'])
            for phone_call in self._get_phone_calls_to_patient().records
            for response in phone_call['responses']
        ]

    def _get_upcoming_appointments(self) -> UpcomingAppointmentRecordSet:
        '''Get all uncancelled upcoming appointments for this patient.

        Returns:
            UpcomingAppointmentRecordSet: A record set containing all uncancelled upcoming
                appointments.
        '''
        return UpcomingAppointmentRecordSet(
            [
                appointment
                for appointment in self.patient.upcoming_appointments
                if appointment['status'] != 'cancelled'
            ]
        )

    def _get_tasks_by_label(self, labels: List[str]) -> TaskRecordSet:
        '''
        Get all open tasks with specified labels.

        Args:
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

    def in_denominator(self) -> bool:
        '''
        Check for patients who:
            - Have not had an annual assessment this year
            - Have had fewer than 5 phone call attempts
            - Do not have an appointment scheduled
            - Do not have a 'non interested' status
            - Do not have an engagement/transition task

        Returns:
            bool: True if the patient satisfies the above condition, False otherwise.
        '''
        phone_calls = self._get_phone_calls_to_patient()
        return (
            not self._get_annual_assessments_between(arrow.get(self._now.year, 1, 1), self._now)
            and len(phone_calls) < 5
            and not self._get_upcoming_appointments()
            and PhoneResponses.REACHED_NOT_INTERESTED not in self._get_phone_call_responses()
            and not self._get_tasks_by_label(ENGAGEMENT_TRANSITION_TASK_LABELS)
        )

    def in_numerator(self) -> bool:
        '''Check for patients who have had a phone call today.

        Returns:
            bool: True if the patient has had a phone call today, False otherwise.
        '''
        phone_calls = self._get_phone_calls_to_patient()
        return bool(phone_calls.after(self._now.replace(hour=0, minute=0, second=0)))

    def compute_results(self) -> ProtocolResult:
        '''
        Computes the results of the protocol for a given patient.

        Returns:
            ProtocolResult: The computed results of the protocol.
        '''
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.next_review = self._now.replace(hour=0, minute=0, second=0).shift(
                    hours=-1, days=1
                )
                result.status = STATUS_SATISFIED
                result.add_narrative('Patient has been called today. Try again tomorrow.')
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative('Patient needs to be called today about an annual assessment.')
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Patient does not need to be called.')

        return result
