from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.utils import Http
from canvas_sdk.v1.data.task import Task

from logger import log


class TaskWebhookNotificationProtocol(BaseProtocol):
    """
    When a task is created or updated, hit a webhook
    """

    RESPONDS_TO = [
        EventType.Name(EventType.TASK_CREATED),
        EventType.Name(EventType.TASK_UPDATED),
    ]

    def compute(self):
        """
        Notify our server of tasks as they are created.
        """
        url = self.secrets["WEBHOOK_NOTIFICATION_URL"]
        auth_token = self.secrets["AUTH_TOKEN"]
        headers = {"Authorization": f"Bearer {auth_token}"}

        verb = 'created' if self.event.type == EventType.TASK_CREATED else 'updated'

        task = Task.objects.select_related("patient").select_related("creator").get(id=self.target)

        patient_details = None
        if task.patient:
            patient_details = {
                "id": task.patient.id,
                "first_name": task.patient.first_name,
                "last_name": task.patient.last_name,
                "birth_date": task.patient.birth_date.isoformat(),
                "sex_at_birth": task.patient.get_sex_at_birth_display(),
            }

        staff_assignee_details = None
        if task.assignee:
            staff_assignee_details = {
                "id": task.assignee.id,
                "first_name": task.assignee.first_name,
                "last_name": task.assignee.last_name,
            }

        payload = {
            "task_id": self.target,
            "event": verb,
            "title": task.title,
            "due_date": task.due.isoformat(),
            "patient": patient_details,
            "creator": {
                "id": task.creator.id,
                "first_name": task.creator.first_name,
                "last_name": task.creator.last_name,
            },
            "assignee": {
                "staff": staff_assignee_details,
                # populate when team is available through the data module;
                "team": None
            }
        }

        http = Http()
        response = http.post(url, json=payload, headers=headers)

        event_name = EventType.Name(self.event.type)

        if response.ok:
            log.info(f"Successfully notified API of {event_name} for task ID {task.id}")
        else:
            log.info(f"Notification of {event_name} for task ID {task.id} unsuccessful. =[")

        return []
