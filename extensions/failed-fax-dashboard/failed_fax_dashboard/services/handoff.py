"""Moving a task to a new owner within what the SDK can do today.

``UpdateTask`` sends a cleared field as ``{"id": None}``, which Canvas rejects, and the
whole update with it. So a move only ever sets the new side:

- to a person: set the assignee (a team on the task stays attached, as for a claimed team task)
- to a team, when no person holds the task: set the team
- to a team, when a person holds it: the person can't be removed, so close their task and
  open a new one for the team, pointing back to the old one
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus, UpdateTask
from canvas_sdk.v1.data import Task, Team

from failed_fax_dashboard.models import FaxAlert
from failed_fax_dashboard.services.util import TEAM_PREFIX, person_name

LABEL = "Failed fax"


@dataclass
class Handoff:
    """The effects of a move, and the id of the task that holds the fax afterwards."""

    effects: list[Effect]
    task_id: str


def to_person(task_id: str, staff_id: str, **fields: Any) -> UpdateTask:
    """Update that gives the task to a person (plus any other fields, such as due or status)."""
    return UpdateTask(id=task_id, assignee_id=staff_id, **fields)


def to_team(
    alert: FaxAlert,
    task: Task | None,
    team: Team,
    *,
    by: str = "",
    author_id: str | None = None,
    due: datetime | None = None,
    reopen: bool = False,
) -> Handoff:
    """Give the alert's task to a team, closing and replacing it when a person holds it.

    ``by`` names who made the move, for the comments. ``due`` and ``reopen`` apply to the
    task that holds the fax afterwards. The alert is updated and saved.
    """
    holder = task.assignee if task is not None else None
    if task is None or holder is None:
        fields: dict[str, Any] = {"team_id": str(team.id)}
        if due is not None:
            fields["due"] = due
        if reopen:
            fields["status"] = TaskStatus.OPEN
        alert.assignee = f"{TEAM_PREFIX}{team.id}"
        alert.save()
        return Handoff([UpdateTask(id=alert.task_id, **fields).apply()], alert.task_id)

    old_id = str(task.id)
    new_id = str(uuid4())
    suffix = f" by {by}" if by else ""
    holder_name = person_name(holder)
    new_fields: dict[str, Any] = {
        "id": new_id,
        "title": task.title,
        "team_id": str(team.id),
        "due": due if due is not None else task.due,
        "labels": [LABEL],
    }
    if task.patient is not None:
        new_fields["patient_id"] = task.patient.id
    effects = [
        UpdateTask(id=old_id, status=TaskStatus.CLOSED).apply(),
        AddTaskComment(
            task_id=old_id,
            body=f"Handed to {team.name}{suffix}. Continued in a new task assigned to {team.name}.",
            author_id=author_id,
        ).apply(),
        AddTask(**new_fields).apply(),
        AddTaskComment(
            task_id=new_id,
            body=(
                f"Continued from a task that was assigned to {holder_name}. "
                "Its comments are on that closed task and on the Failed Faxes dashboard."
            ),
            author_id=author_id,
        ).apply(),
    ]
    earlier = [part for part in alert.previous_task_ids.split(",") if part]
    alert.previous_task_ids = ",".join([*earlier, old_id])
    alert.task_id = new_id
    alert.assignee = f"{TEAM_PREFIX}{team.id}"
    alert.closed = False
    alert.save()
    return Handoff(effects, new_id)
