"""Staff-authed SimpleAPI for the scoring dashboard."""

from __future__ import annotations

import json
import uuid
from datetime import date
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from questionnaire_scoring_dashboard.commands.scoring_trend import ScoringTrendCommand
from questionnaire_scoring_dashboard.config import resolve_instrument
from questionnaire_scoring_dashboard.data.notes import fetch_open_note_rows
from questionnaire_scoring_dashboard.data.observations import fetch_survey_rows
from questionnaire_scoring_dashboard.services.metrics import (
    compute_metrics,
    filter_by_range,
)
from questionnaire_scoring_dashboard.services.notes_select import choose_notes
from questionnaire_scoring_dashboard.services.scoring import build_series
from questionnaire_scoring_dashboard.services.svg_chart import render_line_svg


def _format_change(change: float | None) -> str:
    if change is None:
        return "-"
    if change > 0:
        return f"+{change}"
    return str(change)


def _max_for(label: str) -> int | None:
    return resolve_instrument(label).max_score


def _build_payload(patient_id: str, start: str | None, end: str | None) -> dict:
    """Series + metrics per instrument, filtered to [start, end]."""
    series = build_series(fetch_survey_rows(patient_id))
    today = date.today()
    payload: dict[str, dict] = {}
    for label, points in series.items():
        ranged = filter_by_range(points, start, end)
        payload[label] = {
            "series": ranged,
            "metrics": compute_metrics(ranged, as_of=today),
            "max_score": _max_for(label),
        }
    return payload


class ScoringDashboardAPI(StaffSessionAuthMixin, SimpleAPI):
    @api.get("/")
    def index(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient", "")
        instruments = sorted(build_series(fetch_survey_rows(patient_id)).keys())
        html = render_to_string(
            "templates/dashboard.html",
            context={
                "patient_json": json.dumps(patient_id),
                "instruments_json": json.dumps(instruments),
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/data")
    def data(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient", "")
        start = self.request.query_params.get("start") or None
        end = self.request.query_params.get("end") or None
        payload = _build_payload(patient_id, start, end)
        return [JSONResponse(payload, status_code=HTTPStatus.OK)]

    @api.get("/style.css")
    def get_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("templates/style.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/notes")
    def notes(self) -> list[Response | Effect]:
        patient_id = self.request.query_params.get("patient", "")
        rows = choose_notes(fetch_open_note_rows(patient_id))
        return [JSONResponse(rows, status_code=HTTPStatus.OK)]

    @api.post("/insert")
    def insert(self) -> list[Response | Effect]:
        body = self.request.json()
        note_uuid = (body.get("note_uuid") or "").strip()
        instrument = body.get("instrument") or ""
        patient_id = body.get("patient") or ""
        if not note_uuid or not instrument:
            return [
                JSONResponse(
                    {"error": "note_uuid and instrument required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Patient-scoping: the note must be an open note belonging to this patient.
        valid_note_ids = {n["id"] for n in fetch_open_note_rows(patient_id)}
        if note_uuid not in valid_note_ids:
            return [
                JSONResponse(
                    {"error": "note does not belong to patient"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        start = body.get("start") or None
        end = body.get("end") or None
        series = build_series(fetch_survey_rows(patient_id))
        points = filter_by_range(series.get(instrument, []), start, end)
        metrics = compute_metrics(points, as_of=date.today())
        max_score = _max_for(instrument)

        date_range = (
            f'{points[0]["date"]} - {points[-1]["date"]}' if points else "No data"
        )
        ctx = {
            "title": instrument,
            "date_range": date_range,
            "total": metrics["total"],
            "inserted_on": date.today().isoformat(),
            "latest": "-" if metrics["latest"] is None else metrics["latest"],
            "change": _format_change(metrics["change"]),
            "days_since": "-" if metrics["days_since"] is None else metrics["days_since"],
            "max_score": max_score,
            "svg": render_line_svg(points, max_score),
            "rows": points,
        }
        command = ScoringTrendCommand(
            content=render_to_string("templates/command.html", context=ctx),
            print_content=render_to_string("templates/command_print.html", context=ctx),
        )
        command.command_uuid = str(uuid.uuid4())
        command.note_uuid = note_uuid
        return [command.originate(), JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]
