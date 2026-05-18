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


def _new_branch_id() -> str:
    return "b_" + _uuid_lib.uuid4().hex[:10]


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
    return {
        "version": 1,
        "root": None,  # null until the configurator picks a starting questionnaire
    }


def _validate_pathway(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of validation issues. Empty list means publishable."""
    issues: list[dict[str, Any]] = []
    root = definition.get("root")
    if not root:
        issues.append({"severity": "error", "message": "Pick a starting questionnaire."})
        return issues
    _walk_node(root, ancestors=[], issues=issues)
    return issues


def _walk_node(
    node: dict[str, Any], ancestors: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> None:
    if not isinstance(node, dict):
        issues.append({"severity": "error", "message": "Malformed node."})
        return
    ntype = node.get("type")
    node_id = node.get("node_id", "?")
    if ntype == "questionnaire":
        qid = node.get("questionnaire_id")
        if not qid:
            issues.append(
                {
                    "severity": "error",
                    "node_id": node_id,
                    "message": "Questionnaire node is missing a questionnaire reference.",
                }
            )
        elif not Questionnaire.objects.filter(id=qid).exists():
            issues.append(
                {
                    "severity": "warning",
                    "node_id": node_id,
                    "message": (
                        "Referenced questionnaire is no longer available. "
                        "Branches that condition on it will not evaluate."
                    ),
                }
            )
        branches = node.get("branches", []) or []
        if not branches:
            issues.append(
                {
                    "severity": "error",
                    "node_id": node_id,
                    "message": "Questionnaire node has no branches; every arm must terminate.",
                }
            )
        for b in branches:
            then = b.get("then")
            if not then:
                issues.append(
                    {
                        "severity": "error",
                        "node_id": node_id,
                        "message": "Branch is missing its 'then' target.",
                    }
                )
                continue
            _walk_node(then, ancestors=ancestors + [node], issues=issues)
    elif ntype == "terminal":
        cmd_key = node.get("command_key")
        if not cmd_key:
            issues.append(
                {
                    "severity": "error",
                    "node_id": node_id,
                    "message": "Terminal node is missing a command selection.",
                }
            )
        elif cmd_key not in TERMINAL_COMMANDS:
            issues.append(
                {
                    "severity": "error",
                    "node_id": node_id,
                    "message": f"Unknown terminal command '{cmd_key}'.",
                }
            )
        else:
            spec = TERMINAL_COMMANDS[cmd_key]
            params = node.get("params", {}) or {}
            for field in spec["fields"]:
                if field.get("required") and not str(params.get(field["key"], "")).strip():
                    issues.append(
                        {
                            "severity": "error",
                            "node_id": node_id,
                            "message": f"Terminal '{cmd_key}' is missing required field '{field['key']}'.",
                        }
                    )
    else:
        issues.append(
            {
                "severity": "error",
                "node_id": node_id,
                "message": f"Unknown node type '{ntype}'.",
            }
        )


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
                    options.append(
                        {
                            "id": str(opt.id),
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

    # ---------- Node/branch id helpers ----------

    @api.post("/ids/node")
    def mint_node_id(self) -> list[Response | Effect]:
        return [JSONResponse({"node_id": _new_node_id()})]

    @api.post("/ids/branch")
    def mint_branch_id(self) -> list[Response | Effect]:
        return [JSONResponse({"branch_id": _new_branch_id()})]
