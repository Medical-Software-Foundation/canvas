"""ReportBuilderAPI — serves the SPA shell, static assets, and JSON endpoints."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any, Union

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import (
    HTMLResponse,
    JSONResponse,
    Response,
)
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Staff
from logger import log

from report_builder.reports.export import stream_csv
from report_builder.reports.models import Report, report_from_json, report_to_json
from report_builder.reports.query import safe_run
from report_builder.reports.storage import (
    delete_report,
    get_report,
    list_reports,
    save_report,
    update_report,
)
from report_builder.reports.validate import validate_report
from report_builder.schemas.registry import serialize_registry

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

_STATIC_CONTENT_TYPES: dict[str, str] = {
    "js": "text/javascript",
    "css": "text/css",
}


def _safe_json(data: Any) -> str:
    """Serialize JSON for safe embedding in an HTML script tag."""
    return (
        json.dumps(data)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _bad_request(errors: list[dict[str, str]] | str) -> JSONResponse:
    if isinstance(errors, str):
        errors = [{"path": "", "message": errors}]
    return JSONResponse({"errors": errors}, status_code=HTTPStatus.BAD_REQUEST)


def _not_found() -> JSONResponse:
    return JSONResponse({"error": "Not found"}, status_code=HTTPStatus.NOT_FOUND)


def _internal_error(exc: Exception) -> JSONResponse:
    log.error(f"report-builder: unexpected error: {exc.__class__.__name__}: {exc}")
    return JSONResponse({"error": "Internal error"}, status_code=HTTPStatus.INTERNAL_SERVER_ERROR)


def _parse_body(raw: bytes | str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_as_of_date(raw: str | None) -> date:
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date.today()


def _staff_id(headers: dict[str, str]) -> str:
    return headers.get("canvas-logged-in-user-id", "")


def _staff_label(staff_id: str) -> str:
    if not staff_id:
        return ""
    staff = Staff.objects.filter(id=staff_id).first()
    if staff is None:
        return staff_id
    return getattr(staff, "credentialed_name", None) or f"{staff.first_name} {staff.last_name}".strip()


def _hydrate_report(payload: dict[str, Any]) -> Report:
    """Build a Report from a request body. Raises ValueError on malformed input."""
    return report_from_json(payload)


def _audit_log(
    *,
    event: str,
    staff_id: str,
    report_id: str | None,
    extra: dict[str, Any] | None = None,
) -> None:
    record = {"event": event, "staff_id": staff_id, "report_id": report_id}
    if extra:
        record.update(extra)
    log.info(f"report-builder audit: {json.dumps(record)}")


class ReportBuilderAPI(StaffSessionAuthMixin, SimpleAPI):
    """All HTTP endpoints for the report builder."""

    @api.get("/app")
    def get_app(self) -> list[Union[Response, Effect]]:
        staff_id = _staff_id(dict(self.request.headers))
        staff_name = _staff_label(staff_id)
        initial_data = {
            "staffId": staff_id,
            "staffName": staff_name,
            "today": date.today().isoformat(),
            "cacheBust": _CACHE_BUST,
            "pluginName": "report_builder",
        }
        html = render_to_string(
            "static/index.html",
            {
                "cache_bust": _CACHE_BUST,
                "initial_data": _safe_json(initial_data),
            },
        )
        return [HTMLResponse(html)]

    @api.get("/static/<filename>")
    def get_static(self) -> list[Union[Response, Effect]]:
        filename = self.request.path_params["filename"]
        if "/" in filename or filename.startswith(".."):
            return [Response(b"Not found", status_code=HTTPStatus.NOT_FOUND)]
        extension = filename.rsplit(".", 1)[-1] if "." in filename else ""
        content_type = _STATIC_CONTENT_TYPES.get(extension)
        if not content_type:
            return [Response(b"Not found", status_code=HTTPStatus.NOT_FOUND)]

        content = render_to_string(f"static/{filename}", {"cache_bust": _CACHE_BUST})
        return [
            Response(
                content.encode(),
                status_code=HTTPStatus.OK,
                content_type=content_type,
            )
        ]

    @api.get("/entities")
    def get_entities(self) -> list[Union[Response, Effect]]:
        return [JSONResponse(serialize_registry())]

    @api.get("/reports")
    def list_reports_endpoint(self) -> list[Union[Response, Effect]]:
        return [JSONResponse({"reports": [r.to_dict() for r in list_reports()]})]

    @api.post("/reports")
    def create_report(self) -> list[Union[Response, Effect]]:
        body = _parse_body(self.request.body)
        if body is None:
            return [_bad_request("Request body must be JSON")]
        try:
            report = _hydrate_report(body)
        except ValueError as exc:
            return [_bad_request(str(exc))]

        errors = validate_report(report)
        if errors:
            return [_bad_request([e.to_dict() for e in errors])]

        staff_id = _staff_id(dict(self.request.headers))
        try:
            saved = save_report(report, created_by=staff_id)
        except Exception as exc:
            return [_internal_error(exc)]

        _audit_log(event="create", staff_id=staff_id, report_id=saved.id)
        return [JSONResponse({"report": report_to_json(saved)})]

    @api.get("/reports/<report_id>")
    def get_report_endpoint(self) -> list[Union[Response, Effect]]:
        report_id = self.request.path_params["report_id"]
        report = get_report(report_id)
        if report is None:
            return [_not_found()]
        return [JSONResponse({"report": report_to_json(report)})]

    @api.put("/reports/<report_id>")
    def update_report_endpoint(self) -> list[Union[Response, Effect]]:
        report_id = self.request.path_params["report_id"]
        body = _parse_body(self.request.body)
        if body is None:
            return [_bad_request("Request body must be JSON")]

        body["id"] = report_id
        try:
            report = _hydrate_report(body)
        except ValueError as exc:
            return [_bad_request(str(exc))]

        errors = validate_report(report)
        if errors:
            return [_bad_request([e.to_dict() for e in errors])]

        try:
            saved = update_report(report)
        except Exception as exc:
            return [_internal_error(exc)]

        if saved is None:
            return [_not_found()]

        staff_id = _staff_id(dict(self.request.headers))
        _audit_log(event="update", staff_id=staff_id, report_id=saved.id)
        return [JSONResponse({"report": report_to_json(saved)})]

    @api.delete("/reports/<report_id>")
    def delete_report_endpoint(self) -> list[Union[Response, Effect]]:
        report_id = self.request.path_params["report_id"]
        deleted = delete_report(report_id)
        if not deleted:
            return [_not_found()]
        staff_id = _staff_id(dict(self.request.headers))
        _audit_log(event="delete", staff_id=staff_id, report_id=report_id)
        return [JSONResponse({"deleted": True})]

    @api.post("/reports/preview")
    def preview_report(self) -> list[Union[Response, Effect]]:
        body = _parse_body(self.request.body)
        if body is None:
            return [_bad_request("Request body must be JSON")]

        report_payload = body.get("report")
        if not isinstance(report_payload, dict):
            return [_bad_request("Body must include a 'report' object")]

        try:
            report = _hydrate_report(report_payload)
        except ValueError as exc:
            return [_bad_request(str(exc))]

        errors = validate_report(report)
        if errors:
            return [_bad_request([e.to_dict() for e in errors])]

        as_of = _parse_as_of_date(body.get("as_of_date"))
        page = int(body.get("page") or 1)
        per_page = int(body.get("per_page") or 25)

        try:
            result = safe_run(report, as_of, page, per_page)
        except Exception as exc:
            return [_internal_error(exc)]

        staff_id = _staff_id(dict(self.request.headers))
        _audit_log(
            event="preview",
            staff_id=staff_id,
            report_id=None,
            extra={"as_of_date": as_of.isoformat(), "result_count": result["total"]},
        )
        return [JSONResponse(result)]

    @api.post("/reports/<report_id>/run")
    def run_report(self) -> list[Union[Response, Effect]]:
        report_id = self.request.path_params["report_id"]
        report = get_report(report_id)
        if report is None:
            return [_not_found()]

        body = _parse_body(self.request.body) or {}
        errors = validate_report(report)
        if errors:
            return [_bad_request([e.to_dict() for e in errors])]

        as_of = _parse_as_of_date(body.get("as_of_date"))
        page = int(body.get("page") or 1)
        per_page = int(body.get("per_page") or 100)

        try:
            result = safe_run(report, as_of, page, per_page)
        except Exception as exc:
            return [_internal_error(exc)]

        staff_id = _staff_id(dict(self.request.headers))
        _audit_log(
            event="run",
            staff_id=staff_id,
            report_id=report.id,
            extra={"as_of_date": as_of.isoformat(), "result_count": result["total"]},
        )
        return [JSONResponse(result)]

    @api.get("/reports/<report_id>/export")
    def export_report(self) -> list[Union[Response, Effect]]:
        report_id = self.request.path_params["report_id"]
        report = get_report(report_id)
        if report is None:
            return [_not_found()]

        errors = validate_report(report)
        if errors:
            return [_bad_request([e.to_dict() for e in errors])]

        as_of = _parse_as_of_date(self.request.query_params.get("as_of_date"))

        try:
            body_chunks: list[str] = list(stream_csv(report, as_of))
        except Exception as exc:
            return [_internal_error(exc)]

        body_str = "".join(body_chunks)
        staff_id = _staff_id(dict(self.request.headers))
        _audit_log(
            event="export",
            staff_id=staff_id,
            report_id=report.id,
            extra={"as_of_date": as_of.isoformat()},
        )
        return [
            Response(
                body_str.encode("utf-8"),
                status_code=HTTPStatus.OK,
                headers={
                    "Content-Disposition": f'attachment; filename="{report.name}.csv"',
                },
                content_type="text/csv",
            )
        ]
