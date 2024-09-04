from typing import Optional
from canvas_workflow_kit.constants import CHANGE_TYPE
from canvas_workflow_kit.protocol import (
    STATUS_NOT_APPLICABLE,
    STATUS_SATISFIED,
    ClinicalQualityMeasure,
    ProtocolResult,
)
from canvas_workflow_kit.internal.integration_messages import (
    create_task_payload,
)
import arrow

FALLBACK_STAFF_KEY = '5eede137ecfe4124b8b773040e33be14'
CANVAS_SUPPORT_KEY = '4150cd20de8a470aa570a852859ac87e'
ROLE_DISPLAY = 'Central Primary Care Practitioner'
ROLE_CODE = 'central_primary_care_practitioner'
TASK_LABELS = ['Urgent']
CANVAS_BOT_KEY = '5eede137ecfe4124b8b773040e33be14'


class LabReportTasks(ClinicalQualityMeasure):
    class Meta:
        title = 'Lab Report Task Creation'
        description = (
            'Create task for staff with certain care team role if'
            'lab report becomes assigned to Canvas Support. The purpose'
            'of this protocol is to ensure all lab reports are assigned'
            'to staff who are able to review.'
        )
        version = '1.0.2'
        information = 'https://canvasmedical.com/gallery'
        identifiers = []
        types = []
        compute_on_change_types = [CHANGE_TYPE.LAB_REPORT]
        references = []

    def get_appropriate_care_team_member(self) -> Optional[dict]:
        '''
        Get a member of the care team to assign if they have a role specified by code and display.
        '''
        care_team = self.patient.patient['careTeamMemberships']
        for member in care_team:
            role = member['role']
            if role['code'] == ROLE_CODE and role['display'] == ROLE_DISPLAY:
                return member['staff']['key']
        return None

    def create_tasks(self, ids) -> None:
        '''
        Create a tasks for each lab report assigned to the appropriate care team member if one exists.
        '''
        member_id = self.get_appropriate_care_team_member() or FALLBACK_STAFF_KEY
        tasks = []
        for report_id in ids:
            title = f'Lab Report {report_id} assigned to Canvas Support.'

            # Make sure this task isn't already open to prevent duplicates
            if not self.patient.tasks.filter(title=title, status="OPEN"):
                tasks.append(create_task_payload(
                    patient_key=self.patient.patient['key'],
                    created_by_key=CANVAS_BOT_KEY,
                    status='OPEN',
                    title=title,
                    assignee_identifier=member_id,
                    due=arrow.now().shift(weeks=1).isoformat(),
                    created=arrow.now().isoformat(),
                    labels=TASK_LABELS,
                ))

        self.set_updates(tasks)
        return tasks

    def is_lab_reports_assigned_to_canvas_support(self) -> bool:
        '''Return list of Lab Report IDs that are assigned to Canvas Support.'''
        report_ids = set()
        for lab_report in self.patient.lab_reports:
            for reviewer in lab_report['reviewers']:
                if reviewer['key'] == CANVAS_SUPPORT_KEY:
                    report_ids.add(lab_report['report'])

        return report_ids

    def compute_results(self) -> ProtocolResult:
        result = ProtocolResult()
        if report_ids := self.is_lab_reports_assigned_to_canvas_support():
            tasks = self.create_tasks(report_ids)
            result.status = STATUS_SATISFIED
            result.add_narrative(f'{len(tasks)} tasks created')
        else:
            result.status = STATUS_NOT_APPLICABLE
            result.add_narrative('Report not assigned to Canvas Support, no task created.')
        return result
