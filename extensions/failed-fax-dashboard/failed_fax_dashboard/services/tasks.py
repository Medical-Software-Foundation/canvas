"""The automatic task behind each row: reading it, its comments, and who can be assigned."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from canvas_sdk.v1.data import Staff, Task, TaskComment, Team

from failed_fax_dashboard.models import FaxAlert
from failed_fax_dashboard.services.util import (
    BOT_STAFF_ID,
    STAFF_PREFIX,
    TEAM_PREFIX,
    chunked,
    name_key,
    person_name,
)

ID_CHUNK = 400

ASSIGNEE_STAFF = "staff"
ASSIGNEE_TEAM = "team"


@dataclass(frozen=True)
class TaskInfo:
    """The parts of a Canvas task the dashboard shows."""

    id: str
    title: str
    status: str
    due: datetime | None
    assignee_kind: str
    assignee_id: str
    assignee_name: str
    assignee_sort: str
    patient_key: str
    # Tasks this one replaced after a hand-off to a team, oldest first.
    earlier_ids: tuple[str, ...] = ()
    # The task's number, which is what the chart's task link reads.
    dbid: int = 0

    @property
    def is_open(self) -> bool:
        """Whether the task is still open."""
        return self.status == "OPEN"

    @property
    def url(self) -> str | None:
        """Path that opens the task in the patient's chart (tasks with no patient have none).

        The chart reads ``taskId`` as the task's number and only looks among tasks with the
        ``taskStatus`` given, the same form Canvas's own task permalinks use.
        """
        if not self.patient_key or not self.dbid:
            return None
        return f"/patient/{self.patient_key}?taskId={self.dbid}&taskStatus={self.status}"


def alert_key(source_type: str, item_id: str, e164: str) -> tuple[str, str, str]:
    """Key of the one alert per item and number."""
    return (source_type, item_id, e164)


def load_alerts(item_ids: list[str]) -> dict[tuple[str, str, str], FaxAlert]:
    """Alerts for the given item ids, keyed by (source type, item id, E.164 number)."""
    found: dict[tuple[str, str, str], FaxAlert] = {}
    for chunk in chunked(sorted(set(item_ids)), ID_CHUNK):
        for alert in FaxAlert.objects.filter(item_id__in=chunk):
            found[alert_key(alert.source_type, alert.item_id, alert.fax_number)] = alert
    return found


def task_info(task: Task) -> TaskInfo:
    """Read a task (loaded with its assignee, team, and patient) into a TaskInfo."""
    if task.assignee is not None:
        kind, ident = ASSIGNEE_STAFF, task.assignee.id
        name = person_name(task.assignee)
        sort = name_key(task.assignee.first_name, task.assignee.last_name)
    elif task.team is not None:
        kind, ident = ASSIGNEE_TEAM, str(task.team.id)
        name = task.team.name
        sort = task.team.name.lower()
    else:
        kind, ident, name, sort = "", "", "", ""
    return TaskInfo(
        id=str(task.id),
        title=task.title,
        status=task.status,
        due=task.due,
        assignee_kind=kind,
        assignee_id=ident,
        assignee_name=name,
        assignee_sort=sort,
        patient_key=task.patient.id if task.patient is not None else "",
        dbid=task.dbid,
    )


def load_tasks(task_ids: list[str]) -> dict[str, TaskInfo]:
    """Tasks by id, each with assignee, team, and patient loaded in the same query."""
    found: dict[str, TaskInfo] = {}
    for chunk in chunked(sorted(set(task_ids)), ID_CHUNK):
        for task in Task.objects.filter(id__in=chunk).select_related("assignee", "team", "patient"):
            found[str(task.id)] = task_info(task)
    return found


def team_ids_of(staff: Staff | None) -> set[str]:
    """Ids of the teams the staff member belongs to (``Staff.teams``)."""
    if staff is None:
        return set()
    return {str(team_id) for team_id in staff.teams.values_list("id", flat=True)}


def is_mine(task: TaskInfo | None, staff_id: str, team_ids: set[str]) -> bool:
    """Whether the task is assigned to the staff member or to one of their teams."""
    if task is None:
        return False
    if task.assignee_kind == ASSIGNEE_STAFF:
        return task.assignee_id == staff_id
    if task.assignee_kind == ASSIGNEE_TEAM:
        return task.assignee_id in team_ids
    return False


def task_comments(task_ids: list[str], staff_id: str) -> dict[str, list[dict[str, Any]]]:
    """Comments per task, oldest first. Canvas Bot's are marked automatic."""
    comments: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in task_ids}
    for chunk in chunked(sorted(set(task_ids)), ID_CHUNK):
        rows = (
            TaskComment.objects.filter(task__id__in=chunk)
            .select_related("creator", "task")
            .order_by("created")
        )
        for comment in rows:
            creator = comment.creator
            automatic = creator is None or creator.id == BOT_STAFF_ID
            comments.setdefault(str(comment.task.id), []).append(
                {
                    "id": str(comment.id),
                    "author": "Automatic" if automatic else person_name(creator),
                    "author_id": "" if creator is None else creator.id,
                    "automatic": automatic,
                    "mine": not automatic and creator.id == staff_id,
                    "at": comment.created.isoformat(),
                    "body": comment.body,
                }
            )
    return comments


def assignee_options() -> dict[str, list[dict[str, str]]]:
    """Active staff and teams, as ``staff:<id>`` / ``team:<id>`` values for the pickers."""
    staff = Staff.objects.filter(active=True).order_by("last_name", "first_name")
    teams = Team.objects.order_by("name")
    return {
        "teams": [{"value": f"{TEAM_PREFIX}{team.id}", "name": team.name} for team in teams],
        "staff": [
            {"value": f"{STAFF_PREFIX}{member.id}", "name": person_name(member)} for member in staff
        ],
    }
