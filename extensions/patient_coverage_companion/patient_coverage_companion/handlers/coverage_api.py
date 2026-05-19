"""SimpleAPI for the patient-coverage companion.

Endpoints (all under /plugin-io/api/patient_coverage_companion/app/):

| GET  /                                    | HTML shell                       |
| GET  /main.js                             | JS bundle                        |
| GET  /styles.css                          | CSS                              |
| GET  /data.json?patient_id=X              | Coverages list + dropdowns       |
| GET  /payers/search?q=Y                   | Transactor type-ahead            |
| POST /cards/upload  (upload_files=True)   | Card photo uploads -> S3 keys    |
| POST /coverage                            | Create — CoverageCreateEffect    |
| POST /coverage/<id>                       | Update — CoverageUpdateEffect    |
| POST /coverage/<id>/remove                | Remove                            |
| POST /coverage/<id>/expire                | Expire                            |
| POST /coverage/<id>/photo/<side>/remove   | Remove a single card photo       |
| POST /coverages/reorder                   | Reorder ranks across the stack   |

Authentication: ``StaffSessionAuthMixin``. The platform-side effect
interpreters additionally enforce ``ModelPermissions`` +
``ParentPatientObjectPermissions`` — this handler is not the only line of
defense.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.coverage import Coverage as CoverageEffect, CoverageReorder
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.coverage import (
    Coverage,
    CoverageRank,
    CoverageRelationshipCode,
    CoverageStack,
    CoverageType as CoverageTypeChoice,
    Transactor,
)
from canvas_sdk.v1.data.patient import Patient

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

_RELATIONSHIP_CHOICES = [
    {"value": value, "label": label}
    for value, label in CoverageRelationshipCode.choices
]
_PLAN_TYPE_CHOICES = [
    {"value": value, "label": label}
    for value, label in CoverageTypeChoice.choices
]
_RANK_CHOICES = [
    {"value": int(value), "label": label}
    for value, label in CoverageRank.choices
]


def _serialize_coverage(coverage: Coverage) -> dict[str, Any]:
    """Serialize a Coverage for the form's initial state."""
    snapshot = coverage.snapshot
    front_url = back_url = None
    if snapshot is not None:
        for image in snapshot.snapshotimage_set.all():
            if image.tag == "FRONT_IMAGE" and image.image:
                front_url = image.image.url
            elif image.tag == "BACK_IMAGE" and image.image:
                back_url = image.image.url
    return {
        "id": str(coverage.id),
        "issuer_id": str(coverage.issuer_id) if coverage.issuer_id else None,
        "issuer_name": coverage.issuer.name if coverage.issuer_id else "",
        "subscriber_id": str(coverage.subscriber.id)
        if coverage.subscriber_id and coverage.subscriber
        else None,
        "patient_relationship_to_subscriber": coverage.patient_relationship_to_subscriber,
        "subscriber_identifier": coverage.subscriber_identifier or "",
        "coverage_rank": coverage.coverage_rank,
        "plan_type": coverage.plan_type,
        "coverage_type": coverage.coverage_type or "",
        "id_number": coverage.id_number or "",
        "plan": coverage.plan or "",
        "sub_plan": coverage.sub_plan or "",
        "group": coverage.group or "",
        "sub_group": coverage.sub_group or "",
        "employer": coverage.employer or "",
        "coverage_start_date": coverage.coverage_start_date.isoformat()
        if coverage.coverage_start_date
        else "",
        "coverage_end_date": coverage.coverage_end_date.isoformat()
        if coverage.coverage_end_date
        else "",
        "comments": coverage.comments or "",
        "stack": coverage.stack,
        "card_image_front_url": front_url,
        "card_image_back_url": back_url,
    }


def _parse_date(raw: Any) -> date | None:
    """Parse an ISO date string; return None for blanks. Raises ValueError on bad input."""
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(raw)


def _build_effect_fields(body: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Translate a request body into kwargs for ``CoverageEffect(...)``.

    Returns (kwargs, error_message). Empty / null fields are dropped so the
    update path doesn't clobber unset fields.
    """
    out: dict[str, Any] = {}
    str_fields = (
        "issuer_id",
        "issuer_address_id",
        "issuer_phone_id",
        "subscriber_id",
        "subscriber_identifier",
        "patient_relationship_to_subscriber",
        "coverage_type",
        "plan_type",
        "id_number",
        "plan",
        "sub_plan",
        "group",
        "sub_group",
        "employer",
        "comments",
        "card_image_front_upload_key",
        "card_image_back_upload_key",
    )
    for f in str_fields:
        val = body.get(f)
        if val not in (None, ""):
            out[f] = val
    rank = body.get("coverage_rank")
    if rank not in (None, ""):
        try:
            out["coverage_rank"] = int(rank)
        except (TypeError, ValueError):
            return {}, f"coverage_rank must be an integer, got {rank!r}"
    stack = body.get("stack")
    if stack:
        if stack not in {s.value for s in CoverageStack}:
            return {}, f"stack must be one of {sorted(s.value for s in CoverageStack)}"
        out["stack"] = stack
    try:
        start = _parse_date(body.get("coverage_start_date"))
        end = _parse_date(body.get("coverage_end_date"))
    except ValueError as exc:
        return {}, f"date parse error: {exc}"
    if start is not None:
        out["coverage_start_date"] = start
    if end is not None:
        out["coverage_end_date"] = end
    return out, None


class CoverageAPI(StaffSessionAuthMixin, SimpleAPI):
    """Serves the coverage editor shell, JSON data, and CRUD endpoints."""

    PREFIX = "/app"

    # ---- static assets ----

    @api.get("/")
    def index(self) -> list[Response | Effect]:
        return [
            HTMLResponse(
                render_to_string("static/index.html", {"cache_bust": _CACHE_BUST}),
                status_code=HTTPStatus.OK,
                headers={"Cache-Control": "no-store"},
            )
        ]

    @api.get("/main.js")
    def main_js(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/styles.css")
    def styles_css(self) -> list[Response | Effect]:
        return [
            Response(
                render_to_string("static/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    # ---- data ----

    @api.get("/data.json")
    def data(self) -> list[Response | Effect]:
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id query param is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse({"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND)]

        coverages = (
            Coverage.objects.filter(patient=patient)
            .exclude(stack="REMOVED")
            .select_related("issuer", "subscriber", "snapshot")
            .order_by("stack", "coverage_rank")
        )
        return [
            JSONResponse(
                {
                    "patient_id": str(patient.id),
                    "coverages": [_serialize_coverage(c) for c in coverages],
                    "options": {
                        "relationship": _RELATIONSHIP_CHOICES,
                        "plan_type": _PLAN_TYPE_CHOICES,
                        "rank": _RANK_CHOICES,
                    },
                }
            )
        ]

    @api.get("/payers/search")
    def payers_search(self) -> list[Response | Effect]:
        q = (self.request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return [JSONResponse({"results": []})]
        results = (
            Transactor.objects.filter(name__icontains=q)
            .order_by("name")[:20]
        )
        return [
            JSONResponse(
                {
                    "results": [
                        {"id": str(t.id), "name": t.name, "payer_id": t.payer_id or ""}
                        for t in results
                    ]
                }
            )
        ]

    # ---- card image upload ----

    @api.post("/cards/upload", upload_files=True)
    def upload_cards(self) -> list[Response | Effect]:
        """Accept 'front' and/or 'back' file parts; return S3 keys to the browser
        so the next save call can attach them to the Coverage."""
        parts = {p.name: p.key for p in self.request.form_data()}
        front = parts.get("front")
        back = parts.get("back")
        if not front and not back:
            return [
                JSONResponse(
                    {"error": "expected at least one of 'front' or 'back' file parts"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [JSONResponse({"front_key": front, "back_key": back})]

    # ---- coverage CRUD ----

    @api.post("/coverage")
    def create_coverage(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        patient_id = (body.get("patient_id") or "").strip()
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        fields, err = _build_effect_fields(body)
        if err:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]
        effect = CoverageEffect(patient_id=patient_id, **fields)
        return [
            effect.create(),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/coverage/<coverage_id>")
    def update_coverage(self, coverage_id: str) -> list[Response | Effect]:
        body = self.request.json() or {}
        fields, err = _build_effect_fields(body)
        if err:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]
        effect = CoverageEffect(coverage_id=coverage_id, **fields)
        return [
            effect.update(),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/coverage/<coverage_id>/remove")
    def remove_coverage(self, coverage_id: str) -> list[Response | Effect]:
        return [
            CoverageEffect(coverage_id=coverage_id).remove(),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/coverage/<coverage_id>/expire")
    def expire_coverage(self, coverage_id: str) -> list[Response | Effect]:
        body = self.request.json() or {}
        try:
            end = _parse_date(body.get("coverage_end_date"))
        except ValueError as exc:
            return [
                JSONResponse(
                    {"error": f"coverage_end_date: {exc}"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        if end is None:
            return [
                JSONResponse(
                    {"error": "coverage_end_date is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        return [
            CoverageEffect(coverage_id=coverage_id).expire(coverage_end_date=end),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/coverage/<coverage_id>/photo/<side>/remove")
    def remove_photo(self, coverage_id: str, side: str) -> list[Response | Effect]:
        side_upper = side.upper()
        if side_upper not in {"FRONT", "BACK"}:
            return [
                JSONResponse(
                    {"error": "side must be 'front' or 'back'"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [
            CoverageEffect(coverage_id=coverage_id).remove_photo(side_upper),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/coverages/reorder")
    def reorder(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        patient_id = (body.get("patient_id") or "").strip()
        ordering = body.get("ordering")
        if not patient_id or not isinstance(ordering, list):
            return [
                JSONResponse(
                    {"error": "patient_id and ordering list are required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [
            CoverageReorder(patient_id=patient_id, ordering=ordering).apply(),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]
