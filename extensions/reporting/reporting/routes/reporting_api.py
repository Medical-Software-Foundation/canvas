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
from reporting.services.reports import (
    create as svc_create,
    delete as svc_delete,
    get_visible as svc_get_visible,
    list_visible as svc_list_visible,
    serialize_detail,
    serialize_summary,
    update as svc_update,
)
from reporting.services.dashboards import (
    create as dash_create,
    delete as dash_delete,
    get_visible as dash_get_visible,
    list_visible as dash_list_visible,
    serialize_detail as dash_detail,
    serialize_summary as dash_summary,
    update as dash_update,
)

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


def _field_options(dataset, field) -> list[dict]:
    """Distinct (value, label) options for a reference field, from live instance data."""
    value_path = field.options_value_path
    label_paths = list(field.options_label_paths)
    paths = [value_path] + [p for p in label_paths if p != value_path]
    order = label_paths or [value_path]
    rows = dataset.model.objects.values(*paths).distinct().order_by(*order)
    seen = set()
    out = []
    for r in rows:
        val = r.get(value_path)
        if val is None or val in seen:
            continue
        seen.add(val)
        label = " ".join(str(r.get(p, "")) for p in label_paths).strip() or str(val)
        out.append({"value": str(val), "label": label})
        if len(out) >= 1000:
            break
    return out


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
                            "operators": list(f.operators),
                            "choices": [{"value": v, "label": lbl} for v, lbl in f.choices],
                            "has_options": bool(f.options_value_path)}
                           for f in d.fields.values()],
                "dimensions": [{"key": dim.key, "label": dim.label} for dim in d.dimensions.values()],
                "measures": [{"key": m.key, "label": m.label} for m in d.measures.values()],
            }
            for d in list_datasets()
        ]
        return [JSONResponse({"datasets": payload})]

    @api.get("/field-options")
    def field_options(self) -> list[Response | Effect]:
        params = self.request.query_params
        try:
            dataset = get_dataset(params.get("dataset", ""))
        except KeyError:
            return [JSONResponse({"error": "unknown dataset"}, status_code=HTTPStatus.BAD_REQUEST)]
        field = dataset.fields.get(params.get("field", ""))
        if field is None or not field.options_value_path:
            return [JSONResponse({"error": "field has no options"},
                                 status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"options": _field_options(dataset, field)})]

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
        rows = svc_list_visible(staff_dbid)
        return [JSONResponse({"reports": [serialize_summary(r) for r in rows]})]

    @api.post("/reports")
    def create_report(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        try:
            row = svc_create(
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
        row = svc_get_visible(report_id, staff_dbid)
        if row is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(serialize_detail(row))]

    @api.patch("/reports/<report_id>")
    def update_report(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        report_id = int(self.request.path_params["report_id"])
        fields = {k: body[k] for k in ("name", "category", "visibility", "definition") if k in body}
        ok = svc_update(
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
        ok = svc_delete(report_id, staff_dbid)
        if not ok:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"ok": True})]

    @api.get("/dashboards")
    def list_dashboards(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        rows = dash_list_visible(staff_dbid)
        return [JSONResponse({"dashboards": [dash_summary(r) for r in rows]})]

    @api.post("/dashboards")
    def create_dashboard(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        try:
            row = dash_create(
                staff_dbid=staff_dbid,
                name=body["name"],
                visibility=body.get("visibility", "private"),
                layout=body.get("layout", {"widgets": []}),
                default_period=body.get("default_period", {}),
            )
        except KeyError as exc:
            return [JSONResponse({"error": f"missing field: {exc}"},
                                 status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse({"id": row.dbid}, status_code=HTTPStatus.CREATED)]

    @api.get("/dashboards/<dashboard_id>")
    def get_dashboard(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        row = dash_get_visible(int(self.request.path_params["dashboard_id"]), staff_dbid)
        if row is None:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(dash_detail(row))]

    @api.patch("/dashboards/<dashboard_id>")
    def update_dashboard(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        staff_dbid = _current_staff_dbid(self)
        fields = {k: body[k] for k in ("name", "visibility", "layout", "default_period") if k in body}
        ok = dash_update(
            dashboard_id=int(self.request.path_params["dashboard_id"]),
            staff_dbid=staff_dbid, expected_version=int(body.get("version", 0)), fields=fields,
        )
        if not ok:
            return [JSONResponse({"error": "conflict or not owner"},
                                 status_code=HTTPStatus.CONFLICT)]
        return [JSONResponse({"ok": True})]

    @api.delete("/dashboards/<dashboard_id>")
    def delete_dashboard(self) -> list[Response | Effect]:
        staff_dbid = _current_staff_dbid(self)
        ok = dash_delete(int(self.request.path_params["dashboard_id"]), staff_dbid)
        if not ok:
            return [JSONResponse({"error": "not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"ok": True})]
