"""`find_tasks` chat tool: search tasks (to-dos, reminders)."""

from datetime import date
from typing import Any, ClassVar, Literal  # noqa: UP035

from django.db.models import Q
from pydantic import BaseModel, ConfigDict, Field

from assistant.chat_tools_lib import MAX_RESULT_LIMIT, apply_filter_args
from canvas_sdk.v1.data.task import Task

_TASK_STATUS = Literal["OPEN", "COMPLETED", "CLOSED"]


class FindTasksArgs(BaseModel):
    """Arguments for the `find_tasks` chat tool."""

    model_config = ConfigDict(extra="forbid")

    assignee_id: str | None = Field(None, description="Staff id of the task assignee.")
    patient_id: str | None = None
    status_in: list[_TASK_STATUS] = Field(
        default_factory=lambda: ["OPEN"],  # type: ignore[arg-type]
        description="Defaults to ['OPEN'] when omitted.",
    )
    due_from: date | None = Field(None, description="ISO date YYYY-MM-DD inclusive.")
    due_to: date | None = Field(None, description="ISO date YYYY-MM-DD inclusive.")
    label_names: list[str] | None = Field(
        None,
        description=(
            "Filter to tasks tagged with any of these label names "
            "(case-insensitive exact match)."
        ),
    )
    label_ids: list[str] | None = Field(
        None,
        description="Filter to tasks tagged with any of these TaskLabel ids.",
    )
    limit: int = Field(
        20,
        ge=1,
        le=MAX_RESULT_LIMIT,
        description=f"Max results (default 20, max {MAX_RESULT_LIMIT}).",
    )

    # `label_names` and `label_ids` use M2M joins and require .distinct() —
    # handled outside the lookup map.
    LOOKUPS: ClassVar[dict[str, str]] = {
        "assignee_id": "assignee__id",
        "patient_id": "patient__id",
        "status_in": "status__in",
        "due_from": "due__date__gte",
        "due_to": "due__date__lte",
    }


def find_tasks(instance: Any, args: FindTasksArgs) -> dict:
    """Handler for the `find_tasks` chat tool."""
    qs = apply_filter_args(Task.objects.all(), args, FindTasksArgs.LOOKUPS)

    label_filter_applied = False
    if args.label_ids:
        qs = qs.filter(labels__id__in=args.label_ids)
        label_filter_applied = True
    if args.label_names:
        name_q = Q()
        for n in args.label_names:
            name_q |= Q(labels__name__iexact=n)
        qs = qs.filter(name_q)
        label_filter_applied = True
    if label_filter_applied:
        # M2M joins can duplicate task rows when a task matches multiple labels.
        qs = qs.distinct()

    tasks = list(
        qs.select_related("patient", "assignee")
        .prefetch_related("labels")
        .order_by("due", "-created")[: args.limit]
    )
    results = []
    for t in tasks:
        patient_name = None
        patient_id = None
        if t.patient:
            patient_name = (
                f"{t.patient.first_name or ''} {t.patient.last_name or ''}".strip() or None
            )
            patient_id = t.patient.id
        assignee_name = None
        assignee_id = None
        if t.assignee:
            assignee_name = (
                f"{t.assignee.first_name or ''} {t.assignee.last_name or ''}".strip() or None
            )
            assignee_id = t.assignee.id
        results.append(
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "task_type": t.task_type,  # "T" = Task, "R" = Reminder
                "tag": t.tag or None,
                "due": t.due.isoformat() if t.due else None,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "assignee_id": assignee_id,
                "assignee_name": assignee_name,
                "labels": [{"id": lbl.id, "name": lbl.name} for lbl in t.labels.all()],
            }
        )
    return {"results": results, "count": len(results)}

TOOL_SPEC = {
    "name": "find_tasks",
    "description": "Search for tasks (to-dos, reminders). Defaults to OPEN tasks sorted "
    "by due date (ascending). Filter by assignee (staff_id), patient, "
    "status, due-date range, or labels. When the user asks about 'my "
    "tasks' or 'my to-do list', pass their staff_id as assignee_id. "
    "Results include a `labels` list (id + name) for each task.",
    "args_model": FindTasksArgs,
    "handler": find_tasks,
    "mutates": False,
}
