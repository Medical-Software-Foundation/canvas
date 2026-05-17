from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from clinical_pathways.models import (
    BranchRule,
    Option,
    Pathway,
    Question,
    ResponseType,
    Segment,
)

_API_BASE = "/plugin-io/api/clinical_pathways/builder"


def _parse_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _not_found(resource: str) -> Response:
    return JSONResponse({"error": f"{resource} not found"}, status_code=HTTPStatus.NOT_FOUND)


def _bad_request(message: str) -> Response:
    return JSONResponse({"error": message}, status_code=HTTPStatus.BAD_REQUEST)


def _serialize_option(opt: Option) -> dict[str, Any]:
    return {"dbid": opt.dbid, "label": opt.label, "order": opt.order}


def _serialize_question(q: Question) -> dict[str, Any]:
    return {
        "dbid": q.dbid,
        "text": q.text,
        "response_type": q.response_type,
        "order": q.order,
        "required": q.required,
        "options": [_serialize_option(o) for o in q.options.order_by("order")],
    }


def _serialize_branch(rule: BranchRule) -> dict[str, Any]:
    return {
        "dbid": rule.dbid,
        "from_segment_dbid": rule.from_segment_id,
        "to_segment_dbid": rule.to_segment_id,
        "conditions": rule.conditions,
        "priority": rule.priority,
        "label": rule.label,
    }


def _serialize_segment(seg: Segment, *, include_branches: bool = True) -> dict[str, Any]:
    payload = {
        "dbid": seg.dbid,
        "title": seg.title,
        "order": seg.order,
        "is_entry": seg.is_entry,
        "questions": [_serialize_question(q) for q in seg.questions.order_by("order")],
    }
    if include_branches:
        payload["branches"] = [
            _serialize_branch(r) for r in seg.outgoing_rules.order_by("priority")
        ]
    return payload


def _serialize_pathway(pw: Pathway, *, deep: bool = False) -> dict[str, Any]:
    base = {
        "dbid": pw.dbid,
        "title": pw.title,
        "description": pw.description,
        "recommendation": pw.recommendation,
        "is_active": pw.is_active,
    }
    if deep:
        base["segments"] = [_serialize_segment(s) for s in pw.segments.order_by("order")]
    return base


class BuilderAPI(StaffSessionAuthMixin, SimpleAPI):
    """JSON CRUD endpoints for the pathway builder SPA."""

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
            _serialize_pathway(pw)
            for pw in Pathway.objects.filter(is_active=True).order_by("title")
        ]
        return [JSONResponse({"pathways": rows})]

    @api.post("/pathways")
    def create_pathway(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        title = (body.get("title") or "").strip()
        if not title:
            return [_bad_request("title is required")]
        pw = Pathway(
            title=title,
            description=body.get("description", ""),
            recommendation=body.get("recommendation", ""),
        )
        pw.save()
        return [JSONResponse(_serialize_pathway(pw, deep=True), status_code=HTTPStatus.CREATED)]

    @api.get("/pathways/<pathway_dbid>")
    def get_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [_not_found("Pathway")]
        return [JSONResponse(_serialize_pathway(pw, deep=True))]

    @api.patch("/pathways/<pathway_dbid>")
    def update_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [_not_found("Pathway")]
        body = self.request.json() or {}
        for field in ("title", "description", "recommendation"):
            if field in body:
                setattr(pw, field, body[field])
        if "is_active" in body:
            pw.is_active = bool(body["is_active"])
        pw.save()
        return [JSONResponse(_serialize_pathway(pw, deep=True))]

    @api.delete("/pathways/<pathway_dbid>")
    def delete_pathway(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [_not_found("Pathway")]
        pw.is_active = False
        pw.save()
        return [JSONResponse({"deleted": True})]

    # ---------- Segments ----------

    @api.post("/pathways/<pathway_dbid>/segments")
    def create_segment(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("pathway_dbid"))
        pw = Pathway.objects.filter(dbid=dbid).first()
        if not pw:
            return [_not_found("Pathway")]
        body = self.request.json() or {}
        existing = pw.segments.count()
        seg = Segment(
            pathway=pw,
            title=body.get("title", "Untitled segment"),
            order=body.get("order", existing),
            is_entry=existing == 0,
        )
        seg.save()
        return [JSONResponse(_serialize_segment(seg), status_code=HTTPStatus.CREATED)]

    @api.patch("/segments/<segment_dbid>")
    def update_segment(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("segment_dbid"))
        seg = Segment.objects.filter(dbid=dbid).first()
        if not seg:
            return [_not_found("Segment")]
        body = self.request.json() or {}
        if "title" in body:
            seg.title = body["title"]
        if "order" in body:
            seg.order = int(body["order"])
        if "is_entry" in body and body["is_entry"]:
            Segment.objects.filter(pathway_id=seg.pathway_id, is_entry=True).exclude(
                dbid=seg.dbid
            ).update(is_entry=False)
            seg.is_entry = True
        seg.save()
        return [JSONResponse(_serialize_segment(seg))]

    @api.delete("/segments/<segment_dbid>")
    def delete_segment(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("segment_dbid"))
        seg = Segment.objects.filter(dbid=dbid).first()
        if not seg:
            return [_not_found("Segment")]
        BranchRule.objects.filter(from_segment=seg).delete()
        BranchRule.objects.filter(to_segment=seg).delete()
        for q in seg.questions.all():
            q.options.all().delete()
            q.delete()
        seg.delete()
        return [JSONResponse({"deleted": True})]

    # ---------- Questions ----------

    @api.post("/segments/<segment_dbid>/questions")
    def create_question(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("segment_dbid"))
        seg = Segment.objects.filter(dbid=dbid).first()
        if not seg:
            return [_not_found("Segment")]
        body = self.request.json() or {}
        response_type = body.get("response_type", ResponseType.FREE_TEXT)
        if response_type not in ResponseType.ALL:
            return [_bad_request(f"response_type must be one of {ResponseType.ALL}")]
        q = Question(
            segment=seg,
            text=body.get("text", ""),
            response_type=response_type,
            order=body.get("order", seg.questions.count()),
            required=bool(body.get("required", True)),
        )
        q.save()
        if response_type == ResponseType.YES_NO:
            Option(question=q, label="Yes", order=0).save()
            Option(question=q, label="No", order=1).save()
        return [JSONResponse(_serialize_question(q), status_code=HTTPStatus.CREATED)]

    @api.patch("/questions/<question_dbid>")
    def update_question(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("question_dbid"))
        q = Question.objects.filter(dbid=dbid).first()
        if not q:
            return [_not_found("Question")]
        body = self.request.json() or {}
        if "text" in body:
            q.text = body["text"]
        if "response_type" in body:
            rt = body["response_type"]
            if rt not in ResponseType.ALL:
                return [_bad_request(f"response_type must be one of {ResponseType.ALL}")]
            q.response_type = rt
        if "order" in body:
            q.order = int(body["order"])
        if "required" in body:
            q.required = bool(body["required"])
        q.save()
        return [JSONResponse(_serialize_question(q))]

    @api.delete("/questions/<question_dbid>")
    def delete_question(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("question_dbid"))
        q = Question.objects.filter(dbid=dbid).first()
        if not q:
            return [_not_found("Question")]
        q.options.all().delete()
        q.delete()
        return [JSONResponse({"deleted": True})]

    # ---------- Options ----------

    @api.post("/questions/<question_dbid>/options")
    def create_option(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("question_dbid"))
        q = Question.objects.filter(dbid=dbid).first()
        if not q:
            return [_not_found("Question")]
        body = self.request.json() or {}
        opt = Option(
            question=q,
            label=body.get("label", ""),
            order=body.get("order", q.options.count()),
        )
        opt.save()
        return [JSONResponse(_serialize_option(opt), status_code=HTTPStatus.CREATED)]

    @api.patch("/options/<option_dbid>")
    def update_option(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("option_dbid"))
        opt = Option.objects.filter(dbid=dbid).first()
        if not opt:
            return [_not_found("Option")]
        body = self.request.json() or {}
        if "label" in body:
            opt.label = body["label"]
        if "order" in body:
            opt.order = int(body["order"])
        opt.save()
        return [JSONResponse(_serialize_option(opt))]

    @api.delete("/options/<option_dbid>")
    def delete_option(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("option_dbid"))
        opt = Option.objects.filter(dbid=dbid).first()
        if not opt:
            return [_not_found("Option")]
        opt.delete()
        return [JSONResponse({"deleted": True})]

    # ---------- Branch rules ----------

    @api.get("/segments/<segment_dbid>/branches")
    def list_branches(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("segment_dbid"))
        seg = Segment.objects.filter(dbid=dbid).first()
        if not seg:
            return [_not_found("Segment")]
        rules = [_serialize_branch(r) for r in seg.outgoing_rules.order_by("priority")]
        return [JSONResponse({"branches": rules})]

    @api.post("/segments/<segment_dbid>/branches")
    def create_branch(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("segment_dbid"))
        seg = Segment.objects.filter(dbid=dbid).first()
        if not seg:
            return [_not_found("Segment")]
        body = self.request.json() or {}
        to_dbid = _parse_int(body.get("to_segment_dbid"))
        target = Segment.objects.filter(dbid=to_dbid).first() if to_dbid else None
        if not target:
            return [_bad_request("to_segment_dbid is required and must reference a segment")]
        rule = BranchRule(
            from_segment=seg,
            to_segment=target,
            conditions=body.get("conditions", []),
            priority=int(body.get("priority", 0)),
            label=body.get("label", ""),
        )
        rule.save()
        return [JSONResponse(_serialize_branch(rule), status_code=HTTPStatus.CREATED)]

    @api.patch("/branches/<branch_dbid>")
    def update_branch(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("branch_dbid"))
        rule = BranchRule.objects.filter(dbid=dbid).first()
        if not rule:
            return [_not_found("BranchRule")]
        body = self.request.json() or {}
        if "to_segment_dbid" in body:
            to_dbid = _parse_int(body.get("to_segment_dbid"))
            target = Segment.objects.filter(dbid=to_dbid).first() if to_dbid else None
            if not target:
                return [_bad_request("to_segment_dbid must reference a segment")]
            rule.to_segment = target
        if "conditions" in body:
            rule.conditions = body["conditions"]
        if "priority" in body:
            rule.priority = int(body["priority"])
        if "label" in body:
            rule.label = body["label"]
        rule.save()
        return [JSONResponse(_serialize_branch(rule))]

    @api.delete("/branches/<branch_dbid>")
    def delete_branch(self) -> list[Response | Effect]:
        dbid = _parse_int(self.request.path_params.get("branch_dbid"))
        rule = BranchRule.objects.filter(dbid=dbid).first()
        if not rule:
            return [_not_found("BranchRule")]
        rule.delete()
        return [JSONResponse({"deleted": True})]
