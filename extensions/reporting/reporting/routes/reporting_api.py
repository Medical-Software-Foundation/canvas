"""SimpleAPI: serves the SPA shell, static assets, dataset metadata, and report runs."""

from __future__ import annotations

from datetime import date, datetime, timezone
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Staff

from reporting.datasets import get_dataset, list_datasets
from reporting.query.engine import ReportQuery, run_report
from reporting.query.filters import FilterClause
from reporting.query.periods import PeriodSpec
from reporting.services import reports as report_service

_API_BASE = "/plugin-io/api/reporting/app"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _build_query(dataset_key: str, body: dict) -> ReportQuery:
    dataset = get_dataset(dataset_key)
    measure_key = body["measure_key"]
    if measure_key not in dataset.measures:
        raise ValueError(f"Unknown measure: {measure_key}")
    group_by = body.get("group_by")
    if group_by is not None and group_by not in dataset.dimensions:
        raise ValueError(f"Unknown grouping: {group_by}")
    clauses: list[FilterClause] = []
    for raw in body.get("filters", []):
        if raw["field"] not in dataset.fields:
            raise ValueError(f"Unknown field: {raw['field']}")
        fld = dataset.fields[raw["field"]]
        if raw["operator"] not in fld.operators:
            raise ValueError(f"Operator '{raw['operator']}' not allowed for field '{fld.key}'")
        clauses.append(
            FilterClause(orm_path=fld.orm_path, operator=raw["operator"], values=raw["values"])
        )
    period = None
    if body.get("period"):
        p = body["period"]
        period = PeriodSpec(
            granularity=p.get("granularity", "month"),
            count=int(p.get("count", 3)),
            include_rolling_12=bool(p.get("include_rolling_12", False)),
        )
    return ReportQuery(
        dataset_key=dataset_key,
        filters=clauses,
        measure_key=measure_key,
        group_by=group_by,
        period=period,
    )


def _current_staff_dbid(handler) -> int:
    uuid = handler.request.headers.get("canvas-logged-in-user-id", "")
    return Staff.objects.get(id=uuid).dbid


class ReportingAPI(StaffSessionAuthMixin, SimpleAPI):
    """HTML shell + static assets + JSON endpoints for the Reporting app."""

    PREFIX = "/app"

    @api.get("/home")
    def home(self) -> list[Response | Effect]:
        html = render_to_string("templates/app.html", {"api_base": _API_BASE})
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/app.css")
    def app_css(self) -> list[Response | Effect]:
        css = render_to_string("static/css/app.css")
        return [Response(css.encode(), status_code=HTTPStatus.OK, content_type="text/css")]

    @api.get("/app.js")
    def app_js(self) -> list[Response | Effect]:
        js = render_to_string("static/js/app.js")
        return [
            Response(js.encode(), status_code=HTTPStatus.OK, content_type="application/javascript")
        ]

    @api.get("/datasets")
    def datasets(self) -> list[Response | Effect]:
        payload = [
            {
                "key": d.key,
                "label": d.label,
                "fields": [{"key": f.key, "label": f.label, "type": f.type,
                            "operators": list(f.operators)} for f in d.fields.values()],
                "dimensions": [{"key": dim.key, "label": dim.label} for dim in d.dimensions.values()],
                "measures": [{"key": m.key, "label": m.label} for m in d.measures.values()],
            }
            for d in list_datasets()
        ]
        return [JSONResponse({"datasets": payload})]

    @api.post("/run")
    def run(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        try:
            query = _build_query(body["dataset_key"], body)
            result = run_report(query, anchor=_today())
        except (KeyError, ValueError) as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(result)]

    @api.get("/reports")
    def list_reports(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        rows = report_service.list_visible(staff_dbid)
        return [JSONResponse({"reports": [report_service.serialize_summary(r) for r in rows]})]

    @api.post("/reports")
    def create_report(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        try:
            row = report_service.create(
                staff_dbid=staff_dbid,
                name=body["name"],
                category=body.get("category", ""),
                visibility=body.get("visibility", "private"),
                definition=body.get("definition", {}),
            )
        except KeyError as exc:
            return [JSONResponse({"error": f"missing field: {exc}"},
                                 status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"id": row.dbid}, status_code=HTTPStatus.CREATED)]

    @api.get("/reports/<report_id>")
    def get_report(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        row = report_service.get_visible(report_id, staff_dbid)
        if row is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(report_service.serialize_detail(row))]

    @api.patch("/reports/<report_id>")
    def update_report(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        fields = {k: body[k] for k in ("name", "category", "visibility", "definition") if k in body}
        ok = report_service.update(
            report_id=report_id, staff_dbid=staff_dbid,
            expected_version=int(body.get("version", 0)), fields=fields,
        )
        if not ok:
            return [JSONResponse({"error": "conflict or not owner"},
                                 status_code=HTTPStatus.CONFLICT)]
        return [JSONResponse({"ok": True})]

    @api.delete("/reports/<report_id>")
    def delete_report(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        ok = report_service.delete(report_id, staff_dbid)
        if not ok:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"ok": True})]
