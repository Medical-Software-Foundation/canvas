"""`create_task` chat tool (mutation): queue a new Canvas task or reminder."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task.task import AddTask


class CreateTaskArgs(BaseModel):
    """Arguments for the `create_task` chat tool."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="What needs to be done. Required.")
    assignee_id: str | None = Field(
        None,
        description="Staff id of the person responsible. Omit to leave unassigned.",
    )
    patient_id: str | None = Field(
        None,
        description="Patient id this task is about. Omit if not patient-specific.",
    )
    due: str | None = Field(
        None,
        description=(
            "When the task is due. ISO datetime (YYYY-MM-DDTHH:MM:SS) "
            "or ISO date (YYYY-MM-DD). Optional."
        ),
    )


def create_task(
    instance: Any, args: CreateTaskArgs, staff_id: str | None
) -> tuple[dict, list[Effect]]:
    """Handler for the `create_task` mutation."""
    title = args.title.strip()
    if not title:
        return {"error": "title is required"}, []

    due: datetime | None = None
    if args.due:
        # Accept either an ISO datetime or a bare ISO date.
        try:
            due = datetime.fromisoformat(args.due)
        except ValueError:
            try:
                due = datetime.combine(date.fromisoformat(args.due), datetime.min.time())
            except ValueError:
                return {"error": f"invalid 'due' value: {args.due!r}"}, []

    task_id = str(uuid.uuid4())
    effect = AddTask(
        id=task_id,
        title=title,
        assignee_id=args.assignee_id,
        patient_id=args.patient_id,
        due=due,
        author_id=staff_id,
    ).apply()
    return (
        {
            "created": True,
            "task_id": task_id,
            "title": title,
            "assignee_id": args.assignee_id,
            "patient_id": args.patient_id,
            "due": due.isoformat() if due else None,
            "note": "Task creation queued; will appear in Canvas momentarily.",
        },
        [effect],
    )

TOOL_SPEC = {
    "name": "create_task",
    "description": "Create a new task (to-do or reminder) in Canvas. Mutating tool — "
    "the user must approve before it actually runs. When the user says "
    "'remind me' or 'add a task for myself', set assignee_id to the "
    "requesting staff_id (from the <staff_id> framing). When tied to "
    "the active patient, pass patient_id.",
    "args_model": CreateTaskArgs,
    "handler": create_task,
    "mutates": True,
}
