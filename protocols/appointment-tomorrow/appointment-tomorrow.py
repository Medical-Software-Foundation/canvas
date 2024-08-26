from enum import Enum
from typing import List

import arrow

from canvas_workflow_kit.patient_recordset import (
    InterviewRecordSet,
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

# Replace this with the ID of the Phone Call Disposition Questionnaire.
PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID = 'QUES_PHONE_01'

DEFAULT_TIMEZONE = 'America/Phoenix'


class PhoneQuestions(Enum):
    DISPOSITION = 'QUES_PHONE_01'
    CALL_TO_FROM = 'QUES_PHONE_02'
    COMMENTS = 'QUES_PHONE_16'


class PhoneCallDispositionQuestionnaire(ValueSet):
    VALUE_SET_NAME = 'Phone Call Disposition Questionnaire'
    INTERNAL = {PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID}


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


class AppointmentTomorrow(ClinicalQualityMeasure):
    class Meta:
        title = 'Appointments: Tomorrow'
        description = ()
        version = '1.0.1'
        information = 'https://canvasmedical.com/gallery'
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [
            CHANGE_TYPE.INTERVIEW,
            CHANGE_TYPE.APPOINTMENT,
            CHANGE_TYPE.TASK,
        ]
        references: List[str] = []

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

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
            List[PhoneResponses]: A list of PhoneResponses representing the phone call responses.
        '''
        return [
            PhoneResponses(response['code'])
            for phone_call in self._get_phone_calls_to_patient().records
            for response in phone_call['responses']
        ]

    def _get_upcoming_appointments(self) -> UpcomingAppointmentRecordSet:
        '''Get all uncancelled upcoming appointments for this patient.

        Returns:
            UpcomingAppointmentRecordSet: A record set containing all uncancelled
            upcoming appointments.
        '''
        return UpcomingAppointmentRecordSet(
            [
                appointment
                for appointment in self.patient.upcoming_appointments
                if appointment['status'] != 'cancelled'
            ]
        )

    def in_denominator(self) -> bool:
        '''
        Check for patients with an appointment tomorrow.

        Returns:
            bool: True if the patient has an appointment tomorrow, False otherwise.
        '''
        return any(
            arrow.get(x['startTime']).date() == self._now.shift(days=1).date()
            for x in self._get_upcoming_appointments()
        )

    def in_numerator(self) -> bool:
        '''
        Check for patients who have had either:
            - 1 "patient reached"
            - 2 "phone call attempts".

        Returns:
            bool: True if the patient satisfies the above condition, False otherwise.
        '''
        responses = self._get_phone_call_responses()
        attempts = len(
            [
                response
                for response in responses
                if response
                in [
                    PhoneResponses.NO_ANSWER_MESSAGE,
                    PhoneResponses.NO_ANSWER_NO_MESSAGE,
                ]
            ]
        )
        reached = any(response for response in responses if response == PhoneResponses.REACHED)
        return reached or attempts >= 2

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    'Patient has been contacted or has attempted to be contacted. No action needed.'
                )
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    'Patient has an appointment tomorrow and has not been contacted.'
                )
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Patient does not have an appointment tomorrow.')

        return result
