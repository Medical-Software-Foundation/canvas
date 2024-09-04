from typing import List

import arrow

from canvas_workflow_kit.patient_recordset import TaskRecordSet
from canvas_workflow_kit.protocol import (
    CHANGE_TYPE,
    STATUS_DUE,
    STATUS_NOT_APPLICABLE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult,
)

DEFAULT_TIMEZONE = 'America/Phoenix'
# Replace with the labels of your special tasks.
ENGAGEMENT_TRANSITION_TASK_LABELS = ['Engagement']


class SpecialTasks(ClinicalQualityMeasure):
    class Meta:
        title = 'Engagement: Special Tasks'
        description = ()
        version = '1.0.1'
        information = 'https://canvasmedical.com/gallery'  # Replace with the link to your protocol.
        identifiers: List[str] = []
        types = ['DUO']
        compute_on_change_types = [CHANGE_TYPE.TASK]
        references: List[str] = []

    def _get_timezone(self) -> str:
        return self.settings.get('TIMEZONE') or DEFAULT_TIMEZONE

    @property
    def _now(self) -> arrow.Arrow:
        return arrow.now(self._get_timezone())

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

    def in_denominator(self) -> bool:
        '''
        Check if the patient has a special task at any point in time.

        Returns:
            bool: True if the patient has a special task, False otherwise.
        '''
        return bool(self._get_tasks_by_label(ENGAGEMENT_TRANSITION_TASK_LABELS))

    def in_numerator(self) -> bool:
        '''
        Check if there are patients with a special task that has a due date in the future.

        Returns:
            bool: True if there are patients with a special task in the future, False otherwise.
        '''
        engagement_transition_tasks = self._get_tasks_by_label(ENGAGEMENT_TRANSITION_TASK_LABELS)
        return any(
            arrow.get(task['due']) > self._now for task in engagement_transition_tasks.records
        )

    def compute_results(self) -> ProtocolResult:
        '''Computes the results of the special tasks protocol.

        Returns:
            ProtocolResult: The computed results of the special tasks protocol.
        '''
        result = ProtocolResult()

        if self.in_denominator():
            if self.in_numerator():
                result.status = STATUS_SATISFIED
                result.add_narrative('Special tasks are in the future.')
            else:
                result.due_in = -1
                result.status = STATUS_DUE
                result.add_narrative('Patient has past due special tasks to be addressed.')
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Patient does not have any special tasks.')

        return result
