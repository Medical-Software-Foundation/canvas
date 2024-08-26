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


DEFAULT_TIMEZONE = 'America/Phoenix'
# Replace this with the ID of the Care Team Engagement team.
ENGAGEMENT_TEAM_ID = 'Engagement'
# Replace this with the number of days to look back for task updates (0 = updates today).
TASK_UPDATE_LOOKBACK_DAYS = 0
# Replace this with the ID of the Phone Call Disposition Questionnaire.
PHONE_CALL_DISPOSITION_QUESTIONNAIRE_ID = 'QUES_PHONE_01'
# Replace this with the type of engagement task.
ENGAGEMENT_TASK_TYPE = 'Engagement'


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


class CareTeamEngagement(ClinicalQualityMeasure):
    class Meta:
        title = 'Care Team - Engagement'
        description = ()
        version = '1.0.3'
        information = 'https://canvasmedical.com/gallery'  # Replace with the link to your protocol.
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [CHANGE_TYPE.INTERVIEW, CHANGE_TYPE.APPOINTMENT, CHANGE_TYPE.TASK]
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

    def _get_tasks_by_label(self, labels: List[str]) -> TaskRecordSet:
        '''
        Get all tasks with specified labels.

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

    def _get_engagement_tasks_misassigned(self) -> TaskRecordSet:
        '''Get all engagement tasks not assigned to the engagement team.

        Returns:
            TaskRecordSet: A set of engagement tasks that are not assigned to the engagement team.
        '''
        engagement_tasks = self._get_tasks_by_label([ENGAGEMENT_TASK_TYPE])
        return TaskRecordSet(
            [task for task in engagement_tasks if ENGAGEMENT_TEAM_ID != task['team']]
        )

    def _has_task_update_after(self, start: arrow.Arrow) -> bool:
        '''
        Check if there has been a comment on all engagement tasks after the specified time.

        Args:
            start (arrow.Arrow): The start time to compare against.

        Returns:
            bool: True if there has been a comment on all engagement tasks after the specified time,
        False otherwise.
        '''
        task_updates = self._get_tasks_by_label([ENGAGEMENT_TASK_TYPE])
        task_comments = [comment for task in task_updates for comment in task['comments']]
        return (
            all((arrow.get(comment['created']) > start) for comment in task_comments)
            if task_comments
            else False
        )

    def in_denominator(self) -> bool:
        '''
        Check for patients who:
            - have an engagement task assigned to a team other than the engagement team
            - and have not had an annual assessment.

        Returns:
            bool: True if the patient satisfies the above conditions, False otherwise.
        '''
        return bool(self._get_engagement_tasks_misassigned()) and not bool(
            self._get_annual_assessments()
        )

    def in_numerator(self) -> bool:
        '''
        Check for patients who either:
            - who have received a call in the last TASK_UPDATE_LOOKBACK_DAYS days
            - for whom there’s been a task update in the last TASK_UPDATE_LOOKBACK days.

        Returns:
            bool: True if the patient has satisfied the above condition, False otherwise.
        '''
        phone_calls = self._get_phone_calls_to_patient().after(
            self._now.replace(hour=0, minute=0, second=0).shift(
                days=-(TASK_UPDATE_LOOKBACK_DAYS + 1)
            )
        )
        task_updates = self._has_task_update_after(
            self._now.replace(hour=0, minute=0, second=0).shift(
                days=-(TASK_UPDATE_LOOKBACK_DAYS + 1)
            )
        )
        return bool(task_updates) or bool(phone_calls)

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if self.in_denominator():
            if self.in_numerator():
                result.next_review = self._now.replace(hour=0, minute=0, second=0).shift(
                    hours=-1, days=TASK_UPDATE_LOOKBACK_DAYS + 1
                )
                result.status = STATUS_SATISFIED
                result.add_narrative(
                    (
                        'Patient has been called or has a task update '
                        f'within {TASK_UPDATE_LOOKBACK_DAYS} days. '
                        f'Try again in {TASK_UPDATE_LOOKBACK_DAYS + 1} day(s).'
                    )
                )
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative(
                    (
                        'Patient has an engagement task assigned to the '
                        'wrong team and has not had an annual assessment.'
                    )
                )
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative(
                (
                    'Patient does not have a mis-assigned '
                    'engagement task or has had an annual assessment.'
                )
            )

        return result
