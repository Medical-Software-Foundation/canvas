"""Tests for provider_task_dashboard_companion.handlers.task_dashboard_api."""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from canvas_sdk.effects import EffectType
from canvas_sdk.v1.data.task import Task

from provider_task_dashboard_companion.handlers import task_dashboard_api
from provider_task_dashboard_companion.handlers.task_dashboard_api import (
    TaskDashboardAPI,
    _serialize_comment,
    _serialize_label,
    _serialize_task,
    _split_csv,
)

STAFF_UUID = "00000000-0000-0000-0000-000000000001"
OTHER_STAFF_UUID = "00000000-0000-0000-0000-000000000002"


def _make_api(
    headers: dict | None = None,
    query_params: dict | None = None,
    path_params: dict | None = None,
    json_body: dict | None = None,
) -> TaskDashboardAPI:
    api = TaskDashboardAPI.__new__(TaskDashboardAPI)
    api.request = SimpleNamespace(
        headers=headers or {"canvas-logged-in-user-id": STAFF_UUID},
        query_params=query_params or {},
        path_params=path_params or {},
        json=lambda: json_body if json_body is not None else {},
    )
    return api


class TestSplitCsv:
    def test_empty_returns_empty_list(self) -> None:
        assert _split_csv("") == []
        assert _split_csv(None) == []

    def test_single_value(self) -> None:
        assert _split_csv("OPEN") == ["OPEN"]

    def test_multiple_values_stripped(self) -> None:
        assert _split_csv(" OPEN , CLOSED ,, COMPLETED ") == ["OPEN", "CLOSED", "COMPLETED"]


class TestSerializeLabel:
    def test_serializes_name_and_color(self) -> None:
        label = SimpleNamespace(id="lbl-1", name="Urgent", color="red")
        assert _serialize_label(label) == {"id": "lbl-1", "name": "Urgent", "color": "red"}

    def test_missing_color_defaults_to_empty_string(self) -> None:
        label = SimpleNamespace(id="lbl-1", name="Labeled", color=None)
        assert _serialize_label(label)["color"] == ""


class TestSerializeTask:
    def _base_task(self, **overrides):
        labels_manager = MagicMock()
        labels_manager.all.return_value = []
        defaults = dict(
            id="task-1",
            title="Do thing",
            status="OPEN",
            due=datetime(2026, 4, 17, 15, 0, tzinfo=timezone.utc),
            assignee=SimpleNamespace(id=STAFF_UUID, first_name="Alex", last_name="Park"),
            patient=SimpleNamespace(id="pat-1", first_name="Jane", last_name="Doe"),
            labels=labels_manager,
            comment_count=3,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_mine_and_can_complete_when_open(self) -> None:
        task = self._base_task()
        result = _serialize_task(task, STAFF_UUID)
        assert result["is_mine"] is True
        assert result["can_complete"] is True
        assert result["can_assign_to_me"] is False
        assert result["assignee_id"] == STAFF_UUID
        assert result["assignee_name"] == "Alex Park"
        assert result["patient_id"] == "pat-1"
        assert result["patient_name"] == "Jane Doe"
        assert result["due"] == "2026-04-17T15:00:00+00:00"
        assert result["labels"] == []
        assert result["comment_count"] == 3

    def test_not_mine_allows_assign_to_me(self) -> None:
        task = self._base_task(
            assignee=SimpleNamespace(id=OTHER_STAFF_UUID, first_name="Sam", last_name="Lee"),
        )
        result = _serialize_task(task, STAFF_UUID)
        assert result["is_mine"] is False
        assert result["can_complete"] is False
        assert result["can_assign_to_me"] is True

    def test_unassigned_task(self) -> None:
        task = self._base_task(assignee=None)
        result = _serialize_task(task, STAFF_UUID)
        assert result["assignee_id"] == ""
        assert result["assignee_name"] == ""
        assert result["is_mine"] is False
        assert result["can_assign_to_me"] is True

    def test_null_patient(self) -> None:
        task = self._base_task(patient=None)
        result = _serialize_task(task, STAFF_UUID)
        assert result["patient_id"] == ""
        assert result["patient_name"] == ""

    def test_null_due(self) -> None:
        task = self._base_task(due=None)
        assert _serialize_task(task, STAFF_UUID)["due"] is None

    def test_mine_but_closed_cannot_complete(self) -> None:
        task = self._base_task(status="CLOSED")
        result = _serialize_task(task, STAFF_UUID)
        assert result["is_mine"] is True
        assert result["can_complete"] is False

    def test_falls_back_to_comments_count_when_not_annotated(self) -> None:
        labels_manager = MagicMock()
        labels_manager.all.return_value = []
        comments_manager = MagicMock()
        comments_manager.count.return_value = 7
        task = SimpleNamespace(
            id="task-2",
            title="t",
            status="OPEN",
            due=None,
            assignee=None,
            patient=None,
            labels=labels_manager,
            comments=comments_manager,
        )
        # Note: no comment_count attribute → getattr returns None → hits .count() path.
        result = _serialize_task(task, STAFF_UUID)
        assert result["comment_count"] == 7
        assert comments_manager.mock_calls == [call.count()]

    def test_serializes_labels(self) -> None:
        labels_manager = MagicMock()
        labels_manager.all.return_value = [
            SimpleNamespace(id="l1", name="Urgent", color="red"),
            SimpleNamespace(id="l2", name="Follow-up", color=""),
        ]
        task = self._base_task(labels=labels_manager)
        result = _serialize_task(task, STAFF_UUID)
        assert result["labels"] == [
            {"id": "l1", "name": "Urgent", "color": "red"},
            {"id": "l2", "name": "Follow-up", "color": ""},
        ]


class TestSerializeComment:
    def test_full_comment(self) -> None:
        comment = SimpleNamespace(
            id="c1",
            body="Looks good",
            created=datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc),
            creator=SimpleNamespace(first_name="Alex", last_name="Park"),
        )
        assert _serialize_comment(comment) == {
            "id": "c1",
            "body": "Looks good",
            "created": "2026-04-17T10:00:00+00:00",
            "creator_name": "Alex Park",
        }

    def test_null_creator(self) -> None:
        comment = SimpleNamespace(id="c2", body="…", created=None, creator=None)
        result = _serialize_comment(comment)
        assert result["creator_name"] == ""
        assert result["created"] is None


class TestAuthenticate:
    def test_logged_in(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user={"id": STAFF_UUID})
        assert api.authenticate(creds) is True

    def test_not_logged_in(self) -> None:
        api = _make_api()
        creds = MagicMock(logged_in_user=None)
        assert api.authenticate(creds) is False


class TestIndex:
    def test_returns_html(self) -> None:
        api = _make_api()
        with patch.object(task_dashboard_api, "render_to_string", return_value="<html/>") as mock_render:
            response = api.index()[0]
        assert mock_render.mock_calls == [call("static/index.html", {})]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"<html/>"


class TestFilters:
    def test_returns_statuses_and_active_labels(self) -> None:
        api = _make_api()
        label_queryset = MagicMock()
        label_queryset.order_by.return_value = [
            SimpleNamespace(id="l1", name="Urgent", color="red"),
        ]
        with patch.object(task_dashboard_api, "TaskLabel") as mock_label:
            mock_label.objects.filter.return_value = label_queryset
            response = api.filters()[0]

        assert mock_label.objects.filter.mock_calls[0] == call(
            active=True, modules__contains=["tasks"]
        )
        assert label_queryset.mock_calls == [call.order_by("position", "name")]

        body = json.loads(response.content)
        assert body["statuses"] == ["COMPLETED", "CLOSED", "OPEN"]
        assert body["labels"] == [{"id": "l1", "name": "Urgent", "color": "red"}]


class TestTasks:
    def _setup_queryset(self, tasks):
        qs = MagicMock()
        qs.select_related.return_value = qs
        qs.prefetch_related.return_value = qs
        qs.annotate.return_value = qs
        qs.filter.return_value = qs
        qs.distinct.return_value = qs
        qs.order_by.return_value = qs
        qs.__getitem__.return_value = tasks
        return qs

    def _task(self, **overrides):
        labels_manager = MagicMock()
        labels_manager.all.return_value = []
        defaults = dict(
            id="t1",
            title="Task",
            status="OPEN",
            due=None,
            assignee=SimpleNamespace(id=STAFF_UUID, first_name="Alex", last_name="Park"),
            patient=None,
            labels=labels_manager,
            comment_count=0,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_default_mine_only(self) -> None:
        api = _make_api(query_params={})
        qs = self._setup_queryset([self._task()])
        with patch.object(task_dashboard_api, "Task") as mock_task:
            mock_task.objects.all.return_value = qs
            response = api.tasks()[0]

        # mine=1 branch invokes filter(assignee__id=staff_id)
        assert call.filter(assignee__id=STAFF_UUID) in qs.mock_calls
        assert response.status_code == HTTPStatus.OK
        payload = json.loads(response.content)
        assert len(payload["tasks"]) == 1

    def test_all_tasks_when_mine_off(self) -> None:
        api = _make_api(query_params={"mine": "0"})
        qs = self._setup_queryset([])
        with patch.object(task_dashboard_api, "Task") as mock_task:
            mock_task.objects.all.return_value = qs
            api.tasks()

        # assignee filter must NOT have been called
        assert not any(
            c.args and "assignee__id" in str(c) for c in qs.filter.mock_calls
        )

    def test_status_filter_applied(self) -> None:
        api = _make_api(query_params={"mine": "0", "statuses": "OPEN,BOGUS,CLOSED"})
        qs = self._setup_queryset([])
        with patch.object(task_dashboard_api, "Task") as mock_task:
            mock_task.objects.all.return_value = qs
            api.tasks()

        # Only the valid statuses should have been passed to filter(status__in=...)
        status_filter_calls = [
            c for c in qs.filter.mock_calls if c.kwargs.get("status__in") is not None
        ]
        assert len(status_filter_calls) == 1
        assert set(status_filter_calls[0].kwargs["status__in"]) == {"OPEN", "CLOSED"}

    def test_invalid_statuses_are_skipped(self) -> None:
        api = _make_api(query_params={"mine": "0", "statuses": "BOGUS"})
        qs = self._setup_queryset([])
        with patch.object(task_dashboard_api, "Task") as mock_task:
            mock_task.objects.all.return_value = qs
            api.tasks()

        # no status__in kwargs filter because all were invalid
        assert not any(
            c.kwargs.get("status__in") is not None for c in qs.filter.mock_calls
        )

    def test_labels_filter_applied_with_distinct(self) -> None:
        api = _make_api(query_params={"mine": "0", "labels": "l1,l2"})
        qs = self._setup_queryset([])
        with patch.object(task_dashboard_api, "Task") as mock_task:
            mock_task.objects.all.return_value = qs
            api.tasks()

        label_filter_calls = [
            c for c in qs.filter.mock_calls if c.kwargs.get("labels__id__in") is not None
        ]
        assert len(label_filter_calls) == 1
        assert label_filter_calls[0].kwargs["labels__id__in"] == ["l1", "l2"]


class TestTaskDetail:
    def test_not_found(self) -> None:
        api = _make_api(path_params={"task_id": "missing"})
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.select_related.return_value.prefetch_related.return_value.get.side_effect = Task.DoesNotExist
            response = api.task_detail()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_success_returns_task_and_comments(self) -> None:
        api = _make_api(path_params={"task_id": "t1"})

        labels_manager = MagicMock()
        labels_manager.all.return_value = []
        task = SimpleNamespace(
            id="t1",
            title="T",
            status="OPEN",
            due=None,
            assignee=None,
            patient=None,
            labels=labels_manager,
            comments=MagicMock(count=MagicMock(return_value=0)),
        )

        comments_qs = MagicMock()
        comments_qs.select_related.return_value = comments_qs
        comments_qs.order_by.return_value = [
            SimpleNamespace(
                id="c1",
                body="Hi",
                created=datetime(2026, 4, 17, 9, tzinfo=timezone.utc),
                creator=SimpleNamespace(first_name="Alex", last_name="Park"),
            )
        ]

        with (
            patch.object(Task, "objects") as mock_objects,
            patch.object(task_dashboard_api, "TaskComment") as mock_comment,
        ):
            mock_objects.select_related.return_value.prefetch_related.return_value.get.return_value = task
            mock_comment.objects.filter.return_value = comments_qs
            response = api.task_detail()[0]

        assert response.status_code == HTTPStatus.OK
        body = json.loads(response.content)
        assert body["task"]["id"] == "t1"
        assert body["comments"][0]["body"] == "Hi"


class TestAddComment:
    def test_empty_body_returns_400(self) -> None:
        api = _make_api(path_params={"task_id": "t1"}, json_body={"body": "   "})
        response = api.add_comment()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_none_body_returns_400(self) -> None:
        api = _make_api(path_params={"task_id": "t1"}, json_body=None)
        # Override: json() returns None
        api.request.json = lambda: None
        response = api.add_comment()[0]
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_task_not_found(self) -> None:
        api = _make_api(path_params={"task_id": "missing"}, json_body={"body": "hi"})
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.get.side_effect = Task.DoesNotExist
            response = api.add_comment()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_success_emits_add_task_comment_effect(self) -> None:
        api = _make_api(path_params={"task_id": "t1"}, json_body={"body": "looks good"})
        task = SimpleNamespace(id="t1")
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.get.return_value = task
            result = api.add_comment()

        effect, response = result
        assert effect.type == EffectType.CREATE_TASK_COMMENT
        data = json.loads(effect.payload)["data"]
        assert data["task"]["id"] == "t1"
        assert data["body"] == "looks good"
        assert data["author_id"] == STAFF_UUID

        assert response.status_code == HTTPStatus.ACCEPTED
        body = json.loads(response.content)
        assert body["comment"]["body"] == "looks good"


class TestCompleteTask:
    def test_task_not_found(self) -> None:
        api = _make_api(path_params={"task_id": "missing"})
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.select_related.return_value.get.side_effect = Task.DoesNotExist
            response = api.complete_task()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_not_assignee_returns_403(self) -> None:
        api = _make_api(path_params={"task_id": "t1"})
        task = SimpleNamespace(
            id="t1",
            assignee=SimpleNamespace(id=OTHER_STAFF_UUID),
        )
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.select_related.return_value.get.return_value = task
            response = api.complete_task()[0]
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_unassigned_returns_403(self) -> None:
        api = _make_api(path_params={"task_id": "t1"})
        task = SimpleNamespace(id="t1", assignee=None)
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.select_related.return_value.get.return_value = task
            response = api.complete_task()[0]
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_success_emits_update_task_completed_effect(self) -> None:
        api = _make_api(path_params={"task_id": "t1"})
        task = SimpleNamespace(
            id="t1",
            assignee=SimpleNamespace(id=STAFF_UUID),
        )
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.select_related.return_value.get.return_value = task
            result = api.complete_task()

        effect, response = result
        assert effect.type == EffectType.UPDATE_TASK
        data = json.loads(effect.payload)["data"]
        assert data["id"] == "t1"
        assert data["status"] == "COMPLETED"
        assert response.status_code == HTTPStatus.ACCEPTED


class TestAssignToMe:
    def test_task_not_found(self) -> None:
        api = _make_api(path_params={"task_id": "missing"})
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.get.side_effect = Task.DoesNotExist
            response = api.assign_to_me()[0]
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_success_emits_update_task_assignee_effect(self) -> None:
        api = _make_api(path_params={"task_id": "t1"})
        task = SimpleNamespace(id="t1")
        with patch.object(Task, "objects") as mock_objects:
            mock_objects.get.return_value = task
            result = api.assign_to_me()

        effect, response = result
        assert effect.type == EffectType.UPDATE_TASK
        data = json.loads(effect.payload)["data"]
        assert data["id"] == "t1"
        assert data["assignee"] == {"id": STAFF_UUID}
        assert response.status_code == HTTPStatus.ACCEPTED


class TestStaticEndpoints:
    def test_main_js(self) -> None:
        api = _make_api()
        with patch.object(task_dashboard_api, "render_to_string", return_value="// js"):
            response = api.main_js()[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"// js"
        assert response.headers["Content-Type"] == "text/javascript"

    def test_styles_css(self) -> None:
        api = _make_api()
        with patch.object(task_dashboard_api, "render_to_string", return_value="body{}"):
            response = api.styles_css()[0]
        assert response.status_code == HTTPStatus.OK
        assert response.content == b"body{}"
        assert response.headers["Content-Type"] == "text/css"
