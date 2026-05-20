from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from canvas_sdk.commands import QuestionnaireCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.batch_originate import BatchOriginateCommandEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from clinical_pathways.models import Pathway, PathwayRun

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))
_API_BASE = "/plugin-io/api/clinical_pathways/picker"


def _parse_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class PickerAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the in-note pathway picker modal and starts pathway runs."""

    PREFIX = "/picker"

    # ---------- Modal shell ----------

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        html = render_to_string(
            "static/picker/index.html",
            {"api_base": _API_BASE, "cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        body = render_to_string("static/picker/main.js")
        return [
            Response(
                body.encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        body = render_to_string("static/picker/styles.css")
        return [
            Response(
                body.encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    # ---------- Search ----------

    @api.get("/pathways")
    def search_pathways(self) -> list[Response | Effect]:
        q = (self.request.query_params.get("q") or "").strip()
        qs = Pathway.objects.filter(is_active=True, status="published")
        if q:
            qs = qs.filter(title__icontains=q)
        rows = [
            {"dbid": pw.dbid, "title": pw.title, "description": pw.description}
            for pw in qs.order_by("title")[:50]
        ]
        return [JSONResponse({"pathways": rows})]

    # ---------- Start a run ----------

    @api.post("/start")
    def start_pathway(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        pathway_dbid = _parse_int(body.get("pathway_dbid"))
        note_uuid = (body.get("note_uuid") or "").strip()
        if not note_uuid:
            return [
                JSONResponse(
                    {"error": "note_uuid is required (open the picker from a note)"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if not pathway_dbid:
            return [
                JSONResponse(
                    {"error": "pathway_dbid is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        pw = Pathway.objects.filter(
            dbid=pathway_dbid, is_active=True, status="published"
        ).first()
        if not pw:
            return [
                JSONResponse(
                    {"error": "Pathway not found or not published"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        definition = pw.definition or {}
        if definition.get("version") != 3:
            return [
                JSONResponse(
                    {
                        "error": (
                            "Pathway uses an older format. Open it in the builder "
                            "and re-author it before running."
                        )
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        start_step_id = definition.get("start_step_id")
        steps = definition.get("steps") or []
        start_step = next(
            (s for s in steps if isinstance(s, dict) and s.get("step_id") == start_step_id),
            None,
        )
        if not start_step or not start_step.get("questionnaire_id"):
            return [
                JSONResponse(
                    {"error": "Pathway has no starting step configured."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        start_questionnaire_id = str(start_step["questionnaire_id"])
        # Use pathway_id (column accessor) instead of the instance to dodge a
        # Canvas SDK quirk where the same model class can be loaded under two
        # different module references inside the plugin runner; the FK
        # descriptor's isinstance check then fails on an apparently-correct
        # instance.
        run = PathwayRun(
            note_uuid=note_uuid,
            pathway_id=pw.dbid,
            current_step_id=start_step_id,
            inserted_questionnaires=[start_questionnaire_id],
            status="active",
            captured_responses={},
        )
        run.save()

        questionnaire = QuestionnaireCommand()
        questionnaire.note_uuid = note_uuid
        questionnaire.command_uuid = str(uuid4())
        questionnaire.questionnaire_id = start_questionnaire_id

        return [
            BatchOriginateCommandEffect(commands=[questionnaire]).apply(),
            JSONResponse(
                {
                    "status": "started",
                    "pathway_run_dbid": run.dbid,
                    "pathway_title": pw.title,
                },
                status_code=HTTPStatus.OK,
            ),
        ]
