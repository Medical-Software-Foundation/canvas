from enum import Enum
from typing import List

import arrow

from canvas_workflow_kit.patient_recordset import (
    BillingLineItemRecordSet,
    InterviewRecordSet,
    TaskRecordSet,
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

# Replace this with the code of the questionnaire you want to use.
PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID = 'QUES_PHONE_01'

# Replace this with the current time in the desired timezone.
DEFAULT_TIMEZONE = 'America/Phoenix'

# Replace this with the labels for the transition tasks.
TRANSITION_TASK_LABELS = ['Transition', 'Hospitalized']


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


class PhoneCallDispositionQuestionnaire(ValueSet):
    VALUE_SET_NAME = 'Phone Call Disposition Questionnaire'
    INTERNAL = {PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID}


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


class TransitionsAndHospitalizations(ClinicalQualityMeasure):
    class Meta:
        title = 'Care Team - Transitions and Hospitalizations'
        description = ()
        version = '1.0.1'
        information = 'https://canvasmedical.com/gallery'  # Replace with the link to your protocol.
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [
            CHANGE_TYPE.INTERVIEW,
            CHANGE_TYPE.APPOINTMENT,
            CHANGE_TYPE.TASK,
            CHANGE_TYPE.LAB_REPORT,
            CHANGE_TYPE.IMAGING_REPORT,
            CHANGE_TYPE.BILLING_LINE_ITEM,
        ]
        references: List[str] = []

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

    def _get_annual_assessments(self) -> BillingLineItemRecordSet:
        '''Get annual assessments.

        Returns:
            BillingLineItemRecordSet: The annual assessments for the patient.
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

    def _get_transition_tasks(self) -> TaskRecordSet:
        '''
        Get all open transition tasks for this patient.

        Returns:
            TaskRecordSet: A record set of transition tasks for the patient.
        '''
        open_tasks = self.patient.tasks.filter(
            status='OPEN',
        )
        return TaskRecordSet(
            [
                task
                for task in open_tasks
                if any(label in TRANSITION_TASK_LABELS for label in task['labels'])
            ]
        )

    def in_denominator(self) -> bool:
        '''
        Check for patients:
            - who have a transition task
            - and have not had an annual assessment.

        Returns:
            bool: True if the patient satisfies the above conditions, False otherwise.
        '''
        return bool(self._get_transition_tasks()) and not bool(self._get_annual_assessments())

    def in_numerator(self) -> bool:
        '''
        Check for patients who have been called today.

        Returns:
            bool: True if the patient has been called today, False otherwise.
        '''
        return bool(
            self._get_phone_calls_to_patient().after(self._now.replace(hour=0, minute=0, second=0))
        )

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.next_review = self._now.replace(hour=0, minute=0, second=0).shift(
                    days=1, hours=-1
                )
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    'Patient has a transition task with no annual assessment '
                    'and has been called today. Call again tomorrow.'
                )
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative('Patient has a transition task with no annual assessment.')
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative(
                'Patient does not have a transition task or has had an assessment.'
            )

        return result
