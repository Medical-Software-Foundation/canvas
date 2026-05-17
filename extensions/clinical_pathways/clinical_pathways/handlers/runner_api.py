from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from uuid import uuid4

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from clinical_pathways.models import BranchRule, Pathway, Segment

_API_BASE = "/plugin-io/api/clinical_pathways/runner"

_OP_EQ = "eq"
_OP_CONTAINS = "contains"
_OP_GTE = "gte"
_OP_LTE = "lte"
_OP_IN = "in"


def _parse_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _evaluate_clause(clause: dict[str, Any], answers: dict[int, str]) -> bool:
    qid = _parse_int(clause.get("question_dbid"))
    if qid is None:
        return False
    answer = answers.get(qid)
    if answer is None:
        return False
    op = clause.get("operator")
    value = clause.get("value")
    if op == _OP_EQ:
        return str(answer).strip().lower() == str(value).strip().lower()
    if op == _OP_CONTAINS:
        return str(value).strip().lower() in str(answer).strip().lower()
    if op == _OP_GTE:
        try:
            return float(answer) >= float(value)
        except (TypeError, ValueError):
            return False
    if op == _OP_LTE:
        try:
            return float(answer) <= float(value)
        except (TypeError, ValueError):
            return False
    if op == _OP_IN:
        if not isinstance(value, (list, tuple)):
            return False
        return str(answer).strip().lower() in {str(v).strip().lower() for v in value}
    return False


def _evaluate_rule(rule: BranchRule, answers: dict[int, str]) -> bool:
    clauses = rule.conditions or []
    if not isinstance(clauses, list) or not clauses:
        return False
    return all(_evaluate_clause(c, answers) for c in clauses)


def _next_segment(from_segment: Segment, answers: dict[int, str]) -> Segment | None:
    for rule in from_segment.outgoing_rules.order_by("priority"):
        if _evaluate_rule(rule, answers):
            return rule.to_segment
    return None


def _serialize_segment(seg: Segment) -> dict[str, Any]:
    return {
        "dbid": seg.dbid,
        "title": seg.title,
        "questions": [
            {
                "dbid": q.dbid,
                "text": q.text,
                "response_type": q.response_type,
                "required": q.required,
                "options": [
                    {"dbid": o.dbid, "label": o.label} for o in q.options.order_by("display_order")
                ],
            }
            for q in seg.questions.order_by("display_order")
        ],
    }


class RunnerAPI(StaffSessionAuthMixin, SimpleAPI):
    """Search, segment-step, and complete endpoints for the chart runner."""

    PREFIX = "/runner"

    # ---------- SPA shell ----------

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        html = render_to_string(
            "static/runner/index.html",
            {"api_base": _API_BASE, "cache_bust": _CACHE_BUST},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        body = render_to_string("static/runner/main.js")
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
        body = render_to_string("static/runner/styles.css")
        return [
            Response(
                body.encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    # ---------- Pathway search + entry ----------

    @api.get("/pathways")
    def search_pathways(self) -> list[Response | Effect]:
        q = self.request.query_params.get("q", "").strip()
        qs = Pathway.objects.filter(is_active=True)
        if q:
            qs = qs.filter(title__icontains=q)
        rows = [
            {"dbid": pw.dbid, "title": pw.title, "description": pw.description}
            for pw in qs.order_by("title")[:50]
        ]
        return [JSONResponse({"pathways": rows})]

    @api.get("/pathways/<pathway_dbid>/entry")
    def get_entry_segment(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid, is_active=True).first()
        if not pw:
            return [JSONResponse({"error": "Pathway not found"}, status_code=HTTPStatus.NOT_FOUND)]
        entry = pw.segments.filter(is_entry=True).order_by("display_order").first()
        if not entry:
            entry = pw.segments.order_by("display_order").first()
        if not entry:
            return [JSONResponse({"done": True, "recommendation": pw.recommendation})]
        return [
            JSONResponse(
                {
                    "pathway": {
                        "dbid": pw.dbid,
                        "title": pw.title,
                        "recommendation": pw.recommendation,
                    },
                    "segment": _serialize_segment(entry),
                }
            )
        ]

    # ---------- Segment step ----------

    @api.post("/segments/<segment_dbid>/next")
    def step(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("segment_dbid"))
        seg = Segment.objects.filter(dbid=dbid).first()
        if not seg:
            return [JSONResponse({"error": "Segment not found"}, status_code=HTTPStatus.NOT_FOUND)]
        body = self.request.json() or {}
        raw_responses = body.get("responses", [])
        answers: dict[int, str] = {}
        for r in raw_responses:
            qid = _parse_int(r.get("question_dbid"))
            if qid is None:
                continue
            answers[qid] = str(r.get("answer", ""))
        nxt = _next_segment(seg, answers)
        if not nxt:
            pw = seg.pathway
            return [JSONResponse({"done": True, "recommendation": pw.recommendation})]
        return [JSONResponse({"segment": _serialize_segment(nxt)})]

    # ---------- Complete: originate custom commands ----------

    @api.post("/complete")
    def complete(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        pathway_dbid = _parse_int(body.get("pathway_dbid"))
        note_uuid = (body.get("note_uuid") or "").strip()
        if not note_uuid:
            return [
                JSONResponse(
                    {"error": "note_uuid is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        pw = Pathway.objects.filter(dbid=pathway_dbid).first() if pathway_dbid else None
        if not pw:
            return [
                JSONResponse(
                    {"error": "Pathway not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        responses_trail = body.get("responses_trail", []) or []
        recommendation_text = body.get("recommendation") or pw.recommendation

        qa_context = {
            "pathway_title": pw.title,
            "segments": self._group_responses_by_segment(responses_trail),
        }
        qa_html = render_to_string("templates/qa_trail.html", qa_context)
        qa_print = render_to_string("templates/qa_trail_print.html", qa_context)

        rec_context = {"pathway_title": pw.title, "recommendation": recommendation_text}
        rec_html = render_to_string("templates/recommendation.html", rec_context)
        rec_print = render_to_string("templates/recommendation_print.html", rec_context)

        qa_command = CustomCommand(
            schema_key="pathwayQA",
            content=qa_html,
            print_content=qa_print,
        )
        qa_command.command_uuid = str(uuid4())
        qa_command.note_uuid = note_uuid

        rec_command = CustomCommand(
            schema_key="pathwayRecommendation",
            content=rec_html,
            print_content=rec_print,
        )
        rec_command.command_uuid = str(uuid4())
        rec_command.note_uuid = note_uuid

        return [
            qa_command.originate(),
            rec_command.originate(),
            JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK),
        ]

    @staticmethod
    def _group_responses_by_segment(trail: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse a flat trail into a list of segments, preserving order of first appearance."""
        order: list[int | str] = []
        buckets: dict[int | str, dict[str, Any]] = {}
        for entry in trail:
            seg_key = entry.get("segment_dbid") or entry.get("segment_title") or "_"
            if seg_key not in buckets:
                order.append(seg_key)
                buckets[seg_key] = {
                    "segment_title": entry.get("segment_title", ""),
                    "items": [],
                }
            buckets[seg_key]["items"].append(
                {
                    "question": entry.get("question_text", ""),
                    "answer": entry.get("answer", ""),
                }
            )
        return [buckets[k] for k in order]
