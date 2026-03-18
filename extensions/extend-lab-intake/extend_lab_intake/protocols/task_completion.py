"""Protocol handler for task completion notifications to configured callback."""

from __future__ import annotations

import json
from typing import Any

import requests
from canvas_sdk.effects import Effect, EffectType
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.task import Task
from logger import log

from extend_lab_intake.utils.constants import Secrets, Labels


class TaskCompletionHandler(BaseProtocol):
    """Handler for lab intake task completion events.

    When a lab intake task is completed, this handler notifies the configured
    configured callback URL with the results.
    """

    RESPONDS_TO = EventType.Name(EventType.TASK_COMPLETED)

    def compute(self) -> list[Effect]:
        """Handle task update events.

        Checks if the updated task is a lab intake task that was just completed,
        and if so, sends a notification to the configured callback URL.
        """
        try:
            # Get task details from event
            task_id = self.event.target.id

            # Load the task with related objects to avoid N+1 queries
            task = Task.objects.prefetch_related('labels', 'comments').get(id=task_id)

            # Check if this is a lab intake task
            if not self._is_lab_intake_task(task):
                return []

            # Check if task was just completed
            if task.status != "COMPLETED":
                return []

            log.info(f"Lab intake task {task_id} completed, sending callback")

            # Get callback URL
            callback_url = self.secrets.get(Secrets.CALLBACK_URL)

            if not callback_url:
                log.info("No CALLBACK_URL configured, skipping callback")
                return []

            # Build and send callback
            self._send_callback(callback_url, task)

            return []

        except Task.DoesNotExist:
            log.warning(f"Task {self.event.target.id} not found")
            return []
        except Exception as e:
            log.error(f"Task completion handler error: {e}")
            return []

    def _is_lab_intake_task(self, task: Task) -> bool:
        """Check if the task is a lab intake task."""
        # Check task labels
        try:
            for label in task.labels.all():
                if label.name == Labels.LAB_INTAKE:
                    return True
        except Exception:
            pass

        # Also check task title as fallback
        if task.title and "Lab Intake" in task.title:
            return True

        return False

    def _send_callback(self, callback_url: str, task: Task) -> None:
        """Send completion notification to configured callback callback URL."""
        payload = self._build_callback_payload(task)

        try:
            response = requests.post(
                callback_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code in (200, 201, 202):
                log.info(f"Callback sent successfully to {callback_url}")
            else:
                log.warning(
                    f"Callback returned status {response.status_code}: {response.text}"
                )

        except Exception as e:
            log.error(f"Callback request failed: {e}")

    def _build_callback_payload(self, task: Task) -> dict[str, Any]:
        """Build the callback notification payload."""
        payload: dict[str, Any] = {
            "event": "lab_intake_completed",
            "task_id": str(task.id),
            "status": task.status,
            "title": task.title,
        }

        # Add patient info if linked
        if task.patient_id:
            payload["patient_id"] = str(task.patient_id)

        # Add timestamps
        if task.created:
            payload["created_at"] = task.created.isoformat()
        if task.modified:
            payload["completed_at"] = task.modified.isoformat()

        # Extract any metadata from task comments
        # (The inbound fax handler stores results in comments)
        try:
            if hasattr(task, "comments"):
                comments = list(task.comments.all())
                if comments:
                    # Get most recent comment for summary
                    latest_comment = comments[-1]
                    if "Lab Results Summary" in latest_comment.body:
                        payload["summary"] = latest_comment.body
        except Exception as e:
            log.warning(f"Could not extract task comments: {e}")

        return payload
