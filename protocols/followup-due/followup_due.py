import datetime

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

# Replace with the IDs of the questionnaires you want to use
PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID = 'QUES_PHONE_01'
RISK_STRATIFICATION_QUESTIONNAIRE_ID = 'DUO_QUES_RISK_STRAT_01'
RISK_STRATIFICATION_QUESTION_ID = 'DUO_QUES_RISK_STRAT_02'


DEFAULT_TIMEZONE = 'America/Phoenix'

# -- each of these is the window + 10% (33 days, 66 days, 198 days)
SIX_MONTHS_WINDOW = datetime.timedelta(days=198)
TWO_MONTH_WINDOW = datetime.timedelta(days=66)
NEXT_MONTH_WINDOW = datetime.timedelta(days=33)

LONG_TIME_AGO = arrow.now().shift(years=-10)

DEFAULT_RISK = 'Low'

RISK_WINDOWS = {
    'Low': SIX_MONTHS_WINDOW,
    'Medium': SIX_MONTHS_WINDOW,
    'High Risk': TWO_MONTH_WINDOW,
    'High Risk - Unstable': NEXT_MONTH_WINDOW,
}


class PhoneResponses(Enum):
    REACHED = 'QUES_PHONE_03'
    REACHED_NOT_INTERESTED = 'QUES_PHONE_04'
    NO_ANSWER_MESSAGE = 'QUES_PHONE_05'
    NO_ANSWER_NO_MESSAGE = 'QUES_PHONE_06'
    CALL_BACK_REQUESTED = 'QUES_PHONE_08'
    CALL_TO_PATIENT = 'QUES_PHONE_10'
    CALL_TO_OTHER = 'QUES_PHONE_11'
    FREE_TEXT = 'QUES_PHONE_16'


class PhoneCallDispositionQuestionnaire(ValueSet):
    VALUE_SET_NAME = 'Phone Call Disposition Questionnaire'
    INTERNAL = {PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID}


class RiskStratificationQuestionnaire(ValueSet):
    VALUE_SET_NAME = 'Risk Stratification Questionnaire'
    INTERNAL = {RISK_STRATIFICATION_QUESTIONNAIRE_ID}


class FollowupDue(ClinicalQualityMeasure):
    class Meta:
        title = 'Follow-ups: Follow-up Due'
        description = ()
        version = '1.0.3'
        information = 'https://canvasmedical.com/gallery'  # Replace with the link to your protocol
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [CHANGE_TYPE.INTERVIEW, CHANGE_TYPE.APPOINTMENT]
        references: List[str] = []

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

    def _get_risk_stratification(self, latest_date: arrow.Arrow = LONG_TIME_AGO):
        '''
        Take a set of interviews for a patient and determine the most recent
        risk stratification.

        Args:
            latest_date (arrow.Arrow): The latest date to consider for risk stratification.
                Defaults to LONG_TIME_AGO.

        Returns:
            str: The code representing the most recent risk stratification,
                or DEFAULT_RISK if no risk stratification is found.
        '''
        latest_risk_questionnaire = self.patient.interviews.find(
            RiskStratificationQuestionnaire
        ).last()

        if (
            latest_risk_questionnaire
            and arrow.get(latest_risk_questionnaire['noteTimestamp']) > latest_date
        ):
            return next(
                (
                    response['value']
                    for response in latest_risk_questionnaire['responses']
                    if response['code'] == RISK_STRATIFICATION_QUESTION_ID
                ),
                DEFAULT_RISK,
            )

        return DEFAULT_RISK

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

    def _get_upcoming_appointments(self) -> UpcomingAppointmentRecordSet:
        '''Get all uncancelled upcoming appointments for this patient.

        Returns:
            UpcomingAppointmentRecordSet: A record set containing all
                uncancelled upcoming appointments.
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
        Check for patients who have no follow-up appointment within the risk stratification period.

        Returns:
            bool: True if the patient has no follow-up appointment within the risk stratification
                period, False otherwise.
        '''
        risk_stratification_period_end = self._now + RISK_WINDOWS.get(
            self._get_risk_stratification(), SIX_MONTHS_WINDOW
        )
        return (
            all(
                arrow.get(appointment['startTime']) > risk_stratification_period_end
                for appointment in self.patient.upcoming_appointments
            )
            if self._get_upcoming_appointments()
            else True
        )

    def in_numerator(self) -> bool:
        '''Check for patients who have been called in the past week.

        Returns:
            bool: True if the patient has been called in the past week, False otherwise.
        '''
        return bool(
            self._get_phone_calls_to_patient().after(
                self._now.replace(hour=0, minute=0, second=0).shift(weeks=-1)
            )
        )

    def compute_results(self) -> ProtocolResult:
        '''
        Computes the results of the protocol and returns a ProtocolResult object.

        Returns:
            ProtocolResult: The computed results of the protocol.
        '''
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                next_sunday_evening = self._now.replace(hour=0, minute=0, second=0).shift(
                    hours=-1, days=7 - self._now.weekday()
                )
                result.next_review = next_sunday_evening
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    'Patient has been contacted in the past week. Try again next week.'
                )
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    'Patient has no appointment within their risk '
                    'stratification period. Call them today.'
                )

        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Patient has an appointment within their risk period.')

        return result
