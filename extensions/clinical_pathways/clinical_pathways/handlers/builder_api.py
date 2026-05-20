from __future__ import annotations

import json
import uuid as _uuid_lib
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.questionnaire import Questionnaire

from clinical_pathways.models import Pathway
from clinical_pathways.terminal_commands import TERMINAL_COMMANDS, terminal_command_catalog

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))
_API_BASE = "/plugin-io/api/clinical_pathways/builder"


def _parse_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_step_id() -> str:
    return "s_" + _uuid_lib.uuid4().hex[:10]


def _new_rule_id() -> str:
    return "r_" + _uuid_lib.uuid4().hex[:10]


def _new_recommendation_id() -> str:
    return "rec_" + _uuid_lib.uuid4().hex[:10]


def _serialize_pathway_summary(pw: Pathway) -> dict[str, Any]:
    return {
        "dbid": pw.dbid,
        "title": pw.title,
        "description": pw.description,
        "status": pw.status,
        "updated_at": pw.updated_at.isoformat() if pw.updated_at else None,
    }


def _serialize_pathway_full(pw: Pathway) -> dict[str, Any]:
    base = _serialize_pathway_summary(pw)
    base["definition"] = pw.definition or _empty_definition()
    return base


def _empty_definition() -> dict[str, Any]:
    """Empty v3 pathway document.

    Shape:
      {
        "version": 3,
        "start_step_id": null | "s_...",
        "loaded_questionnaires": [
          { "questionnaire_id": "<uuid>",
            "questionnaire_name_snapshot": "..." }
        ],
        "steps": [
          { "step_id": "s_...",
            "questionnaire_id": "<uuid>",
            "questionnaire_name_snapshot": "...",
            "question_id": "<uuid>",
            "question_name_snapshot": "...",
            "rules": [
              { "rule_id": "r_...", "combinator": "all"|"any",
                "conditions": [{question_id, operator, value_*...}],
                "then": { "type": "step"|"recommendation", "target_id": "..." }
              }
            ],
            "otherwise": { "type": "step"|"recommendation", "target_id": "..." } | null }
        ],
        "recommendations": [
          { "recommendation_id": "rec_...", "name": "...",
            "command_key": "pathway_classification",
            "params": {title, severity, body, recommended_action} }
        ]
      }
    """
    return {
        "version": 3,
        "start_step_id": None,
        "loaded_questionnaires": [],
        "steps": [],
        "recommendations": [],
    }


def _validate_pathway(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of validation issues. Empty list (errors==0) means publishable."""
    issues: list[dict[str, Any]] = []
    if not isinstance(definition, dict):
        issues.append({"severity": "error", "message": "Pathway has no definition yet."})
        return issues
    if definition.get("version") != 3:
        issues.append(
            {
                "severity": "error",
                "message": (
                    "This pathway uses an older format and can't be published. "
                    "Delete and recreate it."
                ),
            }
        )
        return issues

    steps = definition.get("steps") or []
    recommendations = definition.get("recommendations") or []
    start_step_id = definition.get("start_step_id")
    step_ids = {s.get("step_id") for s in steps if isinstance(s, dict)}
    recommendation_ids = {
        r.get("recommendation_id") for r in recommendations if isinstance(r, dict)
    }

    def _check_target(target: Any, ctx: dict[str, str]) -> None:
        if not isinstance(target, dict):
            issues.append({**ctx, "severity": "error", "message": "Routing target is missing."})
            return
        ttype = target.get("type")
        tid = target.get("target_id")
        if ttype == "step":
            if tid not in step_ids:
                issues.append({**ctx, "severity": "error", "message": "Routes to a step that's not in this pathway."})
        elif ttype == "recommendation":
            if tid not in recommendation_ids:
                issues.append({**ctx, "severity": "error", "message": "Routes to a recommendation that's not in this pathway."})
        else:
            issues.append({**ctx, "severity": "error", "message": "Routing target has an unknown type."})

    if not steps:
        issues.append(
            {"severity": "error", "message": "Add at least one step to the pathway."}
        )
    elif not start_step_id or start_step_id not in step_ids:
        issues.append(
            {"severity": "error", "message": "Pick which step the pathway starts with."}
        )

    for step in steps:
        if not isinstance(step, dict):
            issues.append({"severity": "error", "message": "Malformed step entry."})
            continue
        step_id = step.get("step_id", "?")
        qnid = step.get("questionnaire_id")
        qid = step.get("question_id")
        if not qnid:
            issues.append({"severity": "error", "step_id": step_id, "message": "Step is missing its questionnaire reference."})
        elif not Questionnaire.objects.filter(id=qnid).exists():
            issues.append({"severity": "warning", "step_id": step_id, "message": "Referenced questionnaire is no longer available."})
        if not qid:
            issues.append({"severity": "error", "step_id": step_id, "message": "Step is missing its question reference."})

        rules = step.get("rules") or []
        otherwise = step.get("otherwise")
        if not rules and not otherwise:
            issues.append(
                {
                    "severity": "warning",
                    "step_id": step_id,
                    "message": (
                        "Step has no rules and no Otherwise target — the "
                        "pathway will end after this step."
                    ),
                }
            )
        if otherwise is not None:
            _check_target(otherwise, {"step_id": step_id, "context": "otherwise"})
        for rule in rules:
            if not isinstance(rule, dict):
                issues.append({"severity": "error", "step_id": step_id, "message": "Malformed rule entry."})
                continue
            rule_id = rule.get("rule_id", "?")
            combinator = rule.get("combinator")
            if combinator not in ("all", "any"):
                issues.append({"severity": "error", "step_id": step_id, "rule_id": rule_id, "message": "Rule combinator must be 'all' or 'any'."})
            conditions = rule.get("conditions") or []
            if not conditions:
                issues.append({"severity": "error", "step_id": step_id, "rule_id": rule_id, "message": "Rule has no conditions."})
            _check_target(rule.get("then"), {"step_id": step_id, "rule_id": rule_id})

    for rec in recommendations:
        if not isinstance(rec, dict):
            issues.append(
                {"severity": "error", "message": "Malformed recommendation entry."}
            )
            continue
        rec_id = rec.get("recommendation_id", "?")
        cmd_key = rec.get("command_key")
        if not cmd_key:
            issues.append(
                {
                    "severity": "error",
                    "recommendation_id": rec_id,
                    "message": "Recommendation is missing a command type.",
                }
            )
            continue
        if cmd_key not in TERMINAL_COMMANDS:
            issues.append(
                {
                    "severity": "error",
                    "recommendation_id": rec_id,
                    "message": f"Unknown recommendation command '{cmd_key}'.",
                }
            )
            continue
        spec = TERMINAL_COMMANDS[cmd_key]
        params = rec.get("params") or {}
        for field in spec["fields"]:
            if field.get("required") and not str(params.get(field["key"], "")).strip():
                issues.append(
                    {
                        "severity": "error",
                        "recommendation_id": rec_id,
                        "message": (
                            f"Recommendation '{rec.get('name') or rec_id}' is "
                            f"missing required field '{field['key']}'."
                        ),
                    }
                )

    return issues


class BuilderAPI(StaffSessionAuthMixin, SimpleAPI):
    """JSON-document CRUD + catalog endpoints for the pathway builder SPA."""

    PREFIX = "/builder"

    # ---------- SPA shell ----------

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        html = render_to_string(
            "static/builder/index.html",
            {"api_base": _API_BASE, "cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        body = render_to_string("static/builder/main.js")
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
        body = render_to_string("static/builder/styles.css")
        return [
            Response(
                body.encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    # ---------- Pathway CRUD ----------

    @api.get("/pathways")
    def list_pathways(self) -> list[Response | Effect]:
        rows = [
            _serialize_pathway_summary(pw)
            for pw in Pathway.objects.filter(is_active=True).order_by("title")
        ]
        return [JSONResponse({"pathways": rows})]

    @api.post("/pathways")
    def create_pathway(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        title = (body.get("title") or "Untitled pathway").strip() or "Untitled pathway"
        pw = Pathway(
            title=title,
            description=body.get("description", ""),
            status="draft",
            definition=_empty_definition(),
        )
        pw.save()
        return [JSONResponse(_serialize_pathway_full(pw), status_code=HTTPStatus.CREATED)]

    @api.get("/pathways/<pathway_dbid>")
    def get_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(_serialize_pathway_full(pw))]

    @api.put("/pathways/<pathway_dbid>")
    def replace_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        body = self.request.json() or {}
        if "title" in body:
            pw.title = (body["title"] or "").strip() or pw.title
        if "description" in body:
            pw.description = body.get("description") or ""
        if "definition" in body:
            definition = body["definition"]
            if not isinstance(definition, dict):
                return [
                    JSONResponse(
                        {"error": "definition must be a JSON object"},
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                ]
            pw.definition = definition
        pw.save()
        return [JSONResponse(_serialize_pathway_full(pw))]

    @api.delete("/pathways/<pathway_dbid>")
    def delete_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        pw.is_active = False
        pw.status = "draft"
        pw.save()
        return [JSONResponse({"deleted": True})]

    @api.post("/pathways/<pathway_dbid>/publish")
    def publish_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        issues = _validate_pathway(pw.definition or {})
        errors = [i for i in issues if i["severity"] == "error"]
        if errors:
            return [
                JSONResponse(
                    {"published": False, "issues": issues},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        pw.status = "published"
        pw.save()
        return [JSONResponse({"published": True, "issues": issues})]

    @api.post("/pathways/<pathway_dbid>/unpublish")
    def unpublish_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        pw.status = "draft"
        pw.save()
        return [JSONResponse({"unpublished": True})]

    @api.post("/pathways/<pathway_dbid>/validate")
    def validate_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        issues = _validate_pathway(pw.definition or {})
        return [JSONResponse({"issues": issues})]

    # ---------- Catalog: questionnaires + response options ----------

    @api.get("/catalog/questionnaires")
    def list_questionnaires(self) -> list[Response | Effect]:
        q = (self.request.query_params.get("q") or "").strip()
        qs = Questionnaire.objects.filter(
            status="AC",
            can_originate_in_charting=True,
        )
        if q:
            qs = qs.filter(name__icontains=q)
        rows = [
            {"id": str(item.id), "name": item.name, "code": item.code}
            for item in qs.order_by("name")[:50]
        ]
        return [JSONResponse({"questionnaires": rows})]

    @api.get("/catalog/questionnaires/<questionnaire_id>")
    def get_questionnaire_detail(self) -> list[Response | Effect]:
        qid = self.request.path_params.get("questionnaire_id")
        questionnaire = Questionnaire.objects.filter(id=qid).first()
        if not questionnaire:
            return [
                JSONResponse(
                    {"error": "Questionnaire not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]
        questions = []
        for question in questionnaire.questions.all():
            opt_set = question.response_option_set
            options = []
            if opt_set is not None:
                for opt in opt_set.options.all():
                    # ResponseOption does NOT expose `.id` (UUID) in the Canvas
                    # SDK — its primary key is `dbid`. Using `.id` returns
                    # Python None, which stringifies to "None" and silently
                    # collapses every option into the same identifier. Stick
                    # with `dbid` (integer PK, always present). The runtime
                    # evaluator reads `InterviewQuestionResponse.response_option_id`
                    # which is this same column, so both sides match.
                    options.append(
                        {
                            "id": str(opt.dbid),
                            "value": opt.value,
                            "name": opt.name,
                        }
                    )
            questions.append(
                {
                    "id": str(question.id),
                    "name": question.name,
                    "code": question.code,
                    "response_set_type": (opt_set.type if opt_set else None),
                    "response_set_name": (opt_set.name if opt_set else None),
                    "options": options,
                }
            )
        return [
            JSONResponse(
                {
                    "id": str(questionnaire.id),
                    "name": questionnaire.name,
                    "code": questionnaire.code,
                    "questions": questions,
                }
            )
        ]

    # ---------- Catalog: terminal command schemas ----------

    @api.get("/catalog/terminal-commands")
    def list_terminal_commands(self) -> list[Response | Effect]:
        return [JSONResponse({"terminal_commands": terminal_command_catalog()})]

