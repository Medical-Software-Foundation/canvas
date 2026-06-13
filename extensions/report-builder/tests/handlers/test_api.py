"""ReportBuilderAPI tests.

The SimpleAPI base class needs a fully-shaped `event.context`. The helpers
below build a synthetic event and bypass the cached `request` property by
assigning to `handler.__dict__["request"]` directly — this exercises the route
methods without round-tripping through SimpleAPI's routing.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

from report_builder.handlers.api import (
    ReportBuilderAPI,
    _parse_as_of_date,
    _parse_body,
    _safe_json,
    _staff_label,
)
from report_builder.reports.models import Report
from report_builder.reports.storage import ReportMetadata


def _make_request(
    *,
    method: str = "GET",
    path: str = "/entities",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    path_params: dict[str, str] | None = None,
) -> MagicMock:
    req = MagicMock()
    req.method = method
    req.path = path
    req.headers = headers or {}
    req.path_params = path_params or {}
    req.query_params = query or {}
    req.body = json.dumps(body).encode() if body is not None else b""
    return req


def _make_handler(request: MagicMock) -> ReportBuilderAPI:
    event = MagicMock()
    event.context = {"method": request.method, "path": request.path}
    event.type = 0
    handler = ReportBuilderAPI(event=event)
    handler.__dict__["request"] = request
    handler.__dict__["secrets"] = {}
    return handler


def _decode(response: Any) -> dict[str, Any]:
    if isinstance(response.content, bytes):
        data: dict[str, Any] = json.loads(response.content.decode())
        return data
    data = json.loads(response.content)
    return data


def test_safe_json_escapes_angle_brackets() -> None:
    out = _safe_json({"x": "<script>alert(1)</script>"})
    assert "<" not in out
    assert "\\u003c" in out
    assert "\\u003e" in out


def test_parse_body_returns_none_for_empty_bytes() -> None:
    assert _parse_body(None) is None
    assert _parse_body(b"") is None


def test_parse_body_returns_none_for_invalid_json() -> None:
    assert _parse_body(b"not json") is None


def test_parse_body_returns_dict_for_valid_json() -> None:
    assert _parse_body(b'{"a": 1}') == {"a": 1}


def test_parse_body_rejects_non_object_json() -> None:
    assert _parse_body(b"[1, 2]") is None


def test_parse_as_of_date_defaults_to_today_on_empty() -> None:
    from datetime import date

    assert _parse_as_of_date(None) == date.today()
    assert _parse_as_of_date("") == date.today()


def test_parse_as_of_date_falls_back_on_garbage() -> None:
    from datetime import date

    assert _parse_as_of_date("garbage") == date.today()


def test_parse_as_of_date_parses_iso_date() -> None:
    from datetime import date

    assert _parse_as_of_date("2026-05-22") == date(2026, 5, 22)


@patch("report_builder.handlers.api.Staff")
def test_staff_label_returns_credentialed_name(mock_staff: MagicMock) -> None:
    mock_staff.objects.filter.return_value.first.return_value = MagicMock(
        credentialed_name="Dr. Smith"
    )
    assert _staff_label("staff-1") == "Dr. Smith"


def test_staff_label_empty_for_empty_id() -> None:
    assert _staff_label("") == ""


def test_get_entities_returns_registry() -> None:
    handler = _make_handler(_make_request())
    [response] = handler.get_entities()
    body = _decode(response)
    assert response.status_code == HTTPStatus.OK
    assert "entities" in body
    keys = {e["key"] for e in body["entities"]}
    assert keys == {"patient", "appointment", "condition", "note", "lab_order"}


@patch("report_builder.handlers.api.list_reports")
def test_list_reports_endpoint_returns_metadata(mock_list: MagicMock) -> None:
    mock_list.return_value = [
        ReportMetadata(
            id="rpt-1",
            name="Care gap",
            description="",
            root_entity="patient",
            created_by="staff-1",
            created_at="2026-05-22T00:00:00",
            updated_at="2026-05-22T00:00:00",
        )
    ]
    handler = _make_handler(_make_request(path="/reports"))
    [response] = handler.list_reports_endpoint()
    body = _decode(response)
    assert body == {"reports": [mock_list.return_value[0].to_dict()]}


@patch("report_builder.handlers.api.save_report")
def test_create_report_validates_input(mock_save: MagicMock) -> None:
    handler = _make_handler(
        _make_request(
            method="POST",
            path="/reports",
            body={
                "name": "Care gap",
                "root_entity": "patient",
                "conditions": [
                    {"kind": "field", "field": "nonexistent", "op": "eq", "value": "x"}
                ],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
    )
    [response] = handler.create_report()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = _decode(response)
    assert any("nonexistent" in e["message"] for e in body["errors"])
    mock_save.assert_not_called()


@patch("report_builder.handlers.api.save_report")
def test_create_report_persists_and_returns_payload(mock_save: MagicMock) -> None:
    saved = Report(
        id="rpt-1",
        name="Care gap",
        description="",
        root_entity="patient",
        created_by="staff-1",
    )
    mock_save.return_value = saved

    handler = _make_handler(
        _make_request(
            method="POST",
            path="/reports",
            body={
                "name": "Care gap",
                "root_entity": "patient",
                "conditions": [],
                "columns": [],
                "aggregate_columns": [],
            },
            headers={"canvas-logged-in-user-id": "staff-1"},
        )
    )
    [response] = handler.create_report()
    assert response.status_code == HTTPStatus.OK
    assert mock_save.call_count == 1
    assert mock_save.call_args.kwargs == {"created_by": "staff-1"}


def test_create_report_rejects_invalid_json() -> None:
    req = _make_request(method="POST", path="/reports")
    req.body = b"not-json"
    handler = _make_handler(req)
    [response] = handler.create_report()
    assert response.status_code == HTTPStatus.BAD_REQUEST


@patch("report_builder.handlers.api.get_report")
def test_get_report_endpoint_returns_404_for_missing(mock_get: MagicMock) -> None:
    mock_get.return_value = None
    handler = _make_handler(
        _make_request(path="/reports/missing", path_params={"report_id": "missing"})
    )
    [response] = handler.get_report_endpoint()
    assert response.status_code == HTTPStatus.NOT_FOUND


@patch("report_builder.handlers.api.get_report")
def test_get_report_endpoint_returns_report(mock_get: MagicMock) -> None:
    mock_get.return_value = Report(
        id="rpt-1", name="Care gap", description="", root_entity="patient"
    )
    handler = _make_handler(
        _make_request(path="/reports/rpt-1", path_params={"report_id": "rpt-1"})
    )
    [response] = handler.get_report_endpoint()
    body = _decode(response)
    assert body["report"]["id"] == "rpt-1"


@patch("report_builder.handlers.api.delete_report")
def test_delete_report_endpoint_returns_404_when_missing(mock_delete: MagicMock) -> None:
    mock_delete.return_value = False
    handler = _make_handler(
        _make_request(method="DELETE", path="/reports/rpt-1", path_params={"report_id": "rpt-1"})
    )
    [response] = handler.delete_report_endpoint()
    assert response.status_code == HTTPStatus.NOT_FOUND


@patch("report_builder.handlers.api.delete_report")
def test_delete_report_endpoint_returns_ok_on_success(mock_delete: MagicMock) -> None:
    mock_delete.return_value = True
    handler = _make_handler(
        _make_request(method="DELETE", path="/reports/rpt-1", path_params={"report_id": "rpt-1"})
    )
    [response] = handler.delete_report_endpoint()
    assert response.status_code == HTTPStatus.OK
    body = _decode(response)
    assert body == {"deleted": True}


@patch("report_builder.handlers.api.update_report")
@patch("report_builder.handlers.api.get_report")
def test_update_report_endpoint_validates_input(
    mock_get: MagicMock, mock_update: MagicMock
) -> None:
    mock_get.return_value = Report(id="rpt-1", name="Old", description="", root_entity="patient")
    handler = _make_handler(
        _make_request(
            method="PUT",
            path="/reports/rpt-1",
            path_params={"report_id": "rpt-1"},
            body={
                "name": "New",
                "root_entity": "patient",
                "conditions": [
                    {"kind": "field", "field": "nonexistent", "op": "eq", "value": "x"}
                ],
            },
        )
    )
    [response] = handler.update_report_endpoint()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    mock_update.assert_not_called()


@patch("report_builder.handlers.api.update_report")
def test_update_report_endpoint_returns_404_when_missing(mock_update: MagicMock) -> None:
    mock_update.return_value = None
    handler = _make_handler(
        _make_request(
            method="PUT",
            path="/reports/missing",
            path_params={"report_id": "missing"},
            body={"name": "X", "root_entity": "patient"},
        )
    )
    [response] = handler.update_report_endpoint()
    assert response.status_code == HTTPStatus.NOT_FOUND


@patch("report_builder.handlers.api.update_report")
def test_update_report_endpoint_persists_and_returns_payload(mock_update: MagicMock) -> None:
    mock_update.return_value = Report(
        id="rpt-1", name="New", description="", root_entity="patient"
    )
    handler = _make_handler(
        _make_request(
            method="PUT",
            path="/reports/rpt-1",
            path_params={"report_id": "rpt-1"},
            body={"name": "New", "root_entity": "patient"},
        )
    )
    [response] = handler.update_report_endpoint()
    body = _decode(response)
    assert body["report"]["name"] == "New"
    assert mock_update.call_count == 1


@patch("report_builder.handlers.api.safe_run")
def test_preview_report_returns_run_result(mock_run: MagicMock) -> None:
    mock_run.return_value = {
        "rows": [],
        "total": 0,
        "page": 1,
        "per_page": 25,
        "too_large": False,
        "max_rows": 10_000,
        "annotation_columns": [],
    }
    handler = _make_handler(
        _make_request(
            method="POST",
            path="/reports/preview",
            body={
                "report": {"name": "Preview", "root_entity": "patient"},
                "as_of_date": "2026-05-22",
                "page": 1,
                "per_page": 25,
            },
        )
    )
    [response] = handler.preview_report()
    assert response.status_code == HTTPStatus.OK
    assert _decode(response)["total"] == 0
    assert mock_run.call_count == 1


def test_preview_report_rejects_missing_report_key() -> None:
    handler = _make_handler(
        _make_request(method="POST", path="/reports/preview", body={"as_of_date": "2026-05-22"})
    )
    [response] = handler.preview_report()
    assert response.status_code == HTTPStatus.BAD_REQUEST


@patch("report_builder.handlers.api.safe_run")
@patch("report_builder.handlers.api.get_report")
def test_run_report_returns_404_for_missing_report(
    mock_get: MagicMock, mock_run: MagicMock
) -> None:
    mock_get.return_value = None
    handler = _make_handler(
        _make_request(
            method="POST",
            path="/reports/missing/run",
            path_params={"report_id": "missing"},
            body={"as_of_date": "2026-05-22"},
        )
    )
    [response] = handler.run_report()
    assert response.status_code == HTTPStatus.NOT_FOUND
    mock_run.assert_not_called()


@patch("report_builder.handlers.api.safe_run")
@patch("report_builder.handlers.api.get_report")
def test_run_report_returns_run_result(mock_get: MagicMock, mock_run: MagicMock) -> None:
    mock_get.return_value = Report(
        id="rpt-1", name="X", description="", root_entity="patient"
    )
    mock_run.return_value = {
        "rows": [],
        "total": 0,
        "page": 1,
        "per_page": 100,
        "too_large": False,
        "max_rows": 10_000,
        "annotation_columns": [],
    }
    handler = _make_handler(
        _make_request(
            method="POST",
            path="/reports/rpt-1/run",
            path_params={"report_id": "rpt-1"},
            body={"as_of_date": "2026-05-22"},
        )
    )
    [response] = handler.run_report()
    assert response.status_code == HTTPStatus.OK
    assert mock_run.call_count == 1


@patch("report_builder.handlers.api.stream_csv")
@patch("report_builder.handlers.api.get_report")
def test_export_report_streams_csv(mock_get: MagicMock, mock_stream: MagicMock) -> None:
    mock_get.return_value = Report(
        id="rpt-1", name="X", description="", root_entity="patient"
    )
    mock_stream.return_value = iter(["id,first_name\n", "a,Jane\n"])
    handler = _make_handler(
        _make_request(
            path="/reports/rpt-1/export",
            path_params={"report_id": "rpt-1"},
            query={"as_of_date": "2026-05-22"},
        )
    )
    [response] = handler.export_report()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "text/csv"
    assert "X.csv" in response.headers["Content-Disposition"]
    assert response.content == b"id,first_name\na,Jane\n"


@patch("report_builder.handlers.api.get_report")
def test_export_report_returns_404_when_missing(mock_get: MagicMock) -> None:
    mock_get.return_value = None
    handler = _make_handler(
        _make_request(path="/reports/x/export", path_params={"report_id": "x"})
    )
    [response] = handler.export_report()
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_get_static_rejects_path_traversal() -> None:
    handler = _make_handler(
        _make_request(path="/static/../secret", path_params={"filename": "../secret"})
    )
    [response] = handler.get_static()
    assert response.status_code == HTTPStatus.NOT_FOUND


def test_get_static_rejects_unknown_extension() -> None:
    handler = _make_handler(
        _make_request(path="/static/x.png", path_params={"filename": "x.png"})
    )
    [response] = handler.get_static()
    assert response.status_code == HTTPStatus.NOT_FOUND


@patch("report_builder.handlers.api.render_to_string")
def test_get_static_serves_js(mock_render: MagicMock) -> None:
    mock_render.return_value = "// stub"
    handler = _make_handler(
        _make_request(path="/static/app.js", path_params={"filename": "app.js"})
    )
    [response] = handler.get_static()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "text/javascript"
    assert mock_render.call_args.args[0] == "static/app.js"
    assert "cache_bust" in mock_render.call_args.args[1]


@patch("report_builder.handlers.api._staff_label")
@patch("report_builder.handlers.api.render_to_string")
def test_get_app_renders_template(mock_render: MagicMock, mock_label: MagicMock) -> None:
    mock_render.return_value = "<html></html>"
    mock_label.return_value = "Dr. Smith"
    handler = _make_handler(
        _make_request(path="/app", headers={"canvas-logged-in-user-id": "staff-1"})
    )
    [response] = handler.get_app()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"] == "text/html"
    assert response.content == b"<html></html>"
    # context dict passed to template includes cache_bust + initial_data
    template_ctx = mock_render.call_args.args[1]
    assert "cache_bust" in template_ctx
    initial = json.loads(template_ctx["initial_data"])
    assert initial["staffId"] == "staff-1"
    assert initial["staffName"] == "Dr. Smith"
