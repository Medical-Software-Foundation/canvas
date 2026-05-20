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


def _new_node_id() -> str:
    return "n_" + _uuid_lib.uuid4().hex[:10]


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
    """Empty v2 pathway document.

    Shape:
      {
        "version": 2,
        "start_node_id": null | "n_...",
        "nodes": [
          { "node_id": "n_...", "questionnaire_id": "<uuid>",
            "questionnaire_name_snapshot": "...",
            "rules": [
              { "rule_id": "r_...", "combinator": "all"|"any",
                "conditions": [{question_id, operator, value_*...}],
                "then": { "type": "node"|"recommendation", "target_id": "..." }
              }
            ] }
        ],
        "recommendations": [
          { "recommendation_id": "rec_...", "name": "...",
            "command_key": "pathway_classification",
            "params": {title, severity, body, recommended_action} }
        ]
      }
    """
    return {
        "version": 2,
        "start_node_id": None,
        "nodes": [],
        "recommendations": [],
    }


def _validate_pathway(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of validation issues. Empty list (errors==0) means publishable."""
    issues: list[dict[str, Any]] = []
    if not isinstance(definition, dict):
        issues.append({"severity": "error", "message": "Pathway has no definition yet."})
        return issues
    if definition.get("version") != 2:
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

    nodes = definition.get("nodes") or []
    recommendations = definition.get("recommendations") or []
    start_node_id = definition.get("start_node_id")
    node_ids = {n.get("node_id") for n in nodes if isinstance(n, dict)}
    recommendation_ids = {
        r.get("recommendation_id") for r in recommendations if isinstance(r, dict)
    }

    if not nodes:
        issues.append(
            {"severity": "error", "message": "Add a starting questionnaire to the pathway."}
        )
    elif not start_node_id or start_node_id not in node_ids:
        issues.append(
            {
                "severity": "error",
                "message": "Pick which questionnaire the pathway starts with.",
            }
        )

    for node in nodes:
        if not isinstance(node, dict):
            issues.append({"severity": "error", "message": "Malformed node entry."})
            continue
        node_id = node.get("node_id", "?")
        qid = node.get("questionnaire_id")
        if not qid:
            issues.append(
                {
                    "severity": "error",
                    "node_id": node_id,
                    "message": "Node is missing a questionnaire reference.",
                }
            )
        elif not Questionnaire.objects.filter(id=qid).exists():
            issues.append(
                {
                    "severity": "warning",
                    "node_id": node_id,
                    "message": (
                        "Referenced questionnaire is no longer available. "
                        "Rules that condition on it will not evaluate."
                    ),
                }
            )
        rules = node.get("rules") or []
        if not rules:
            issues.append(
                {
                    "severity": "warning",
                    "node_id": node_id,
                    "message": (
                        "Questionnaire has no rules — this arm will end after "
                        "the questionnaire is committed without emitting a "
                        "recommendation."
                    ),
                }
            )
        for rule in rules:
            if not isinstance(rule, dict):
                issues.append(
                    {
                        "severity": "error",
                        "node_id": node_id,
                        "message": "Malformed rule entry.",
                    }
                )
                continue
            rule_id = rule.get("rule_id", "?")
            combinator = rule.get("combinator")
            if combinator not in ("all", "any"):
                issues.append(
                    {
                        "severity": "error",
                        "node_id": node_id,
                        "rule_id": rule_id,
                        "message": "Rule combinator must be either 'all' or 'any'.",
                    }
                )
            conditions = rule.get("conditions") or []
            if not conditions:
                issues.append(
                    {
                        "severity": "error",
                        "node_id": node_id,
                        "rule_id": rule_id,
                        "message": "Rule has no conditions.",
                    }
                )
            then = rule.get("then") or {}
            target_type = then.get("type")
            target_id = then.get("target_id")
            if target_type == "node":
                if target_id not in node_ids:
                    issues.append(
                        {
                            "severity": "error",
                            "node_id": node_id,
                            "rule_id": rule_id,
                            "message": "Rule routes to a questionnaire that's not in this pathway.",
                        }
                    )
            elif target_type == "recommendation":
                if target_id not in recommendation_ids:
                    issues.append(
                        {
                            "severity": "error",
                            "node_id": node_id,
                            "rule_id": rule_id,
                            "message": "Rule routes to a recommendation that's not in this pathway.",
                        }
                    )
            else:
                issues.append(
                    {
                        "severity": "error",
                        "node_id": node_id,
                        "rule_id": rule_id,
                        "message": "Rule is missing its 'then' target.",
                    }
                )

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

