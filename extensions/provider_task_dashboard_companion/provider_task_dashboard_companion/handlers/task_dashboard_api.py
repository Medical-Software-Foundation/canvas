from datetime import datetime, timezone
from http import HTTPStatus

from django.db.models import Count

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.effects.task import AddTaskComment, UpdateTask
from canvas_sdk.effects.task import TaskStatus as EffectTaskStatus
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.task import Task, TaskComment, TaskLabel, TaskStatus

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

ALLOWED_STATUSES = {s.value for s in TaskStatus}


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v for v in (item.strip() for item in value.split(",")) if v]


def _serialize_label(label: TaskLabel) -> dict:
    return {
        "id": str(label.id),
        "name": label.name,
        "color": label.color or "",
    }


def _serialize_task(task: Task, logged_in_staff_id: str) -> dict:
    assignee = task.assignee
    patient = task.patient
    assignee_uuid = str(assignee.id) if assignee else ""
    is_mine = assignee_uuid == logged_in_staff_id
    comment_count = getattr(task, "comment_count", None)
    if comment_count is None:
        comment_count = task.comments.count()
    return {
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "due": task.due.isoformat() if task.due else None,
        "assignee_id": assignee_uuid,
        "assignee_name": (
            f"{assignee.first_name} {assignee.last_name}".strip() if assignee else ""
        ),
        "patient_id": str(patient.id) if patient else "",
        "patient_name": (
            f"{patient.first_name} {patient.last_name}".strip() if patient else ""
        ),
        "labels": [_serialize_label(lbl) for lbl in task.labels.all()],
        "comment_count": comment_count,
        "is_mine": is_mine,
        "can_complete": is_mine and task.status == TaskStatus.OPEN,
        "can_assign_to_me": assignee_uuid != logged_in_staff_id,
    }


def _serialize_comment(comment: TaskComment) -> dict:
    creator = comment.creator
    return {
        "id": str(comment.id),
        "body": comment.body,
        "created": comment.created.isoformat() if comment.created else None,
        "creator_name": (
            f"{creator.first_name} {creator.last_name}".strip() if creator else ""
        ),
    }


class TaskDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the task dashboard companion UI and JSON data."""

    PREFIX = "/app"

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/filters")
    def filters(self) -> list[Response | Effect]:
        labels = (
            TaskLabel.objects.filter(active=True, modules__contains=["tasks"])
            .order_by("position", "name")
        )
        return [
            JSONResponse(
                {
                    "statuses": [s.value for s in TaskStatus],
                    "labels": [_serialize_label(lbl) for lbl in labels],
                }
            )
        ]

    @api.get("/tasks")
    def tasks(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        params = self.request.query_params

        qs = (
            Task.objects.all()
            .select_related("assignee", "patient")
            .prefetch_related("labels")
            .annotate(comment_count=Count("comments"))
        )

        if params.get("mine", "1") == "1":
            qs = qs.filter(assignee__id=staff_id)

        statuses = [s for s in _split_csv(params.get("statuses")) if s in ALLOWED_STATUSES]
        if statuses:
            qs = qs.filter(status__in=statuses)

        label_ids = _split_csv(params.get("labels"))
        if label_ids:
            qs = qs.filter(labels__id__in=label_ids).distinct()

        qs = qs.order_by("due", "-modified")[:500]

        return [JSONResponse({"tasks": [_serialize_task(t, staff_id) for t in qs]})]

    @api.get("/tasks/<task_id>")
    def task_detail(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        task_id = self.request.path_params["task_id"]

        try:
            task = (
                Task.objects.select_related("assignee", "patient")
                .prefetch_related("labels")
                .get(id=task_id)
            )
        except Task.DoesNotExist:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        comments = (
            TaskComment.objects.filter(task=task)
            .select_related("creator")
            .order_by("created")
        )

        return [
            JSONResponse(
                {
                    "task": _serialize_task(task, staff_id),
                    "comments": [_serialize_comment(c) for c in comments],
                }
            )
        ]

    @api.post("/tasks/<task_id>/comments")
    def add_comment(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        task_id = self.request.path_params["task_id"]

        body = (self.request.json() or {}).get("body", "").strip()
        if not body:
            return [
                JSONResponse(
                    {"error": "body is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        effect = AddTaskComment(task_id=str(task.id), body=body, author_id=staff_id)
        return [
            effect.apply(),
            JSONResponse(
                {
                    "comment": {
                        "body": body,
                        "creator_name": "",
                        "created": None,
                    }
                },
                status_code=HTTPStatus.ACCEPTED,
            ),
        ]

    @api.post("/tasks/<task_id>/complete")
    def complete_task(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        task_id = self.request.path_params["task_id"]

        try:
            task = Task.objects.select_related("assignee").get(id=task_id)
        except Task.DoesNotExist:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        if not task.assignee or str(task.assignee.id) != staff_id:
            return [
                JSONResponse(
                    {"error": "Only the assignee can mark a task complete"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        effect = UpdateTask(id=str(task.id), status=EffectTaskStatus.COMPLETED)
        return [
            effect.apply(),
            JSONResponse({"status": "COMPLETED"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/tasks/<task_id>/assign-to-me")
    def assign_to_me(self) -> list[Response | Effect]:
        staff_id = self.request.headers["canvas-logged-in-user-id"]
        task_id = self.request.path_params["task_id"]

        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return [JSONResponse({"error": "Task not found"}, status_code=HTTPStatus.NOT_FOUND)]

        effect = UpdateTask(id=str(task.id), assignee_id=staff_id)
        return [
            effect.apply(),
            JSONResponse({"assignee_id": staff_id}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
