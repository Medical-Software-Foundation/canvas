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

from pydantic import ValidationError as PydanticValidationError

from canvas_sdk.effects import Effect
from canvas_sdk.effects.coverage import Coverage as CoverageEffect, CoverageReorder
from canvas_sdk.effects.patient_identification_card import (
    PatientIdentificationCard as PatientIdentificationCardEffect,
)
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
from canvas_sdk.v1.data.patient import Patient, PatientIdentificationCard

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

# Fields the user must supply to create a new coverage. Mirrors the SDK's
# Coverage._validate_create checks; surfacing them here lets us return a
# structured field-level 400 before invoking the SDK (which would otherwise
# raise a hard-to-parse pydantic ValidationError).
_CREATE_REQUIRED_FIELDS = {
    "issuer_id": "Payer",
    "id_number": "Member ID",
    "coverage_rank": "Rank",
    "plan_type": "Plan type",
    "patient_relationship_to_subscriber": "Relationship to subscriber",
}


def _has_rank_conflict(
    *, patient_id: str, coverage_rank: int, stack: str
) -> bool:
    """Return True if an active coverage already occupies (rank, stack) for
    the patient. Mirrors the interpreter's rank-uniqueness check so we can
    surface the conflict as an inline field error before the async effect
    fires (otherwise the user sees a misleading 'Saved.' banner)."""
    return (
        Coverage.objects.filter(
            patient__id=patient_id,
            coverage_rank=coverage_rank,
            stack=stack,
        )
        .exclude(stack="REMOVED")
        .exists()
    )


def _field_errors_from_pydantic(exc: PydanticValidationError) -> dict[str, str]:
    """Map a pydantic ValidationError into a {field_name: message} dict.

    Pydantic surfaces each error with a ``loc`` tuple — for our flat models
    the first element is the field name. For multi-field rules (which use a
    synthetic ``loc``) we fall back to a generic ``__form__`` key.
    """
    field_errors: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc") or ()
        msg = err.get("msg") or "invalid"
        key = str(loc[0]) if loc else "__form__"
        # First error wins per field; collapse duplicates from nested rules.
        field_errors.setdefault(key, msg)
    return field_errors


def _serialize_coverage(coverage: Coverage) -> dict[str, Any]:
    """Serialize a Coverage for the form's initial state."""
    snapshot = coverage.snapshot
    front_url = back_url = None
    if snapshot is not None:
        # The SDK declares SnapshotImage.snapshot FK with related_name="images",
        # so the reverse manager is `snapshot.images`, not `snapshotimage_set`.
        # SDK SnapshotImage.image is a CharField (path); use the image_url
        # property to get a presigned URL.
        for image in snapshot.images.all():
            if image.tag == "FRONT_IMAGE":
                front_url = image.image_url
            elif image.tag == "BACK_IMAGE":
                back_url = image.image_url
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
        results = Transactor.objects.filter(name__icontains=q).order_by("name")[:20]
        # The SDK Transactor's PK is `dbid` (BigAutoField), not `id` — there's
        # no UUID externally-exposable identifier on Transactor at the SDK
        # surface, so we ship the numeric PK back to the browser and the
        # interpreter resolves it by Transactor.id lookup.
        return [
            JSONResponse(
                {
                    "results": [
                        {"id": str(t.dbid), "name": t.name, "payer_id": t.payer_id or ""}
                        for t in results
                    ]
                }
            )
        ]

    # ---- card image upload ----

    @api.post("/cards/upload", upload_files=True)
    def upload_cards(self) -> list[Response | Effect]:
        """Accept any named file parts; return the S3 keys to the browser so
        the next save call can attach them via an effect. Used by both the
        Coverage flow (``front`` / ``back``) and the ID card flow (``image``).
        """
        form = self.request.form_data()
        keys: dict[str, str] = {}
        for name in form:
            part = form[name]
            key = getattr(part, "key", None)
            if key:
                keys[name] = key
        failures = self.request.upload_failures()
        if not keys:
            return [
                JSONResponse(
                    {
                        "error": "expected at least one file part",
                        "failures": failures or None,
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        # Return both shapes:
        #   - keys: {<part_name>: <s3_key>, ...} for callers that handle
        #     arbitrary field names (ID card flow uses "image").
        #   - front_key / back_key for backwards compatibility with the
        #     Coverage card flow.
        return [
            JSONResponse(
                {
                    "keys": keys,
                    "front_key": keys.get("front"),
                    "back_key": keys.get("back"),
                }
            )
        ]

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

        missing = {
            name: f"{label} is required."
            for name, label in _CREATE_REQUIRED_FIELDS.items()
            if not fields.get(name)
        }
        if missing:
            return [
                JSONResponse(
                    {
                        "error": "Please fill in the required fields.",
                        "field_errors": missing,
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        # Pre-validate the rank/stack collision the interpreter will check.
        # Without this the effect interpreter rejects async, the browser
        # has already gotten a 202, and the user sees a success banner
        # for a write that silently never happened.
        rank_conflict = _has_rank_conflict(
            patient_id=patient_id,
            coverage_rank=fields["coverage_rank"],
            stack=fields.get("stack") or "IN_USE",
        )
        if rank_conflict:
            return [
                JSONResponse(
                    {
                        "error": "Rank already taken.",
                        "field_errors": {
                            "coverage_rank": (
                                f"Patient already has a rank-{fields['coverage_rank']} "
                                f"coverage in stack {fields.get('stack') or 'IN_USE'}. "
                                f"Pick a different rank, or remove the existing one first."
                            ),
                        },
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            effect = CoverageEffect(patient_id=patient_id, **fields).create()
        except PydanticValidationError as exc:
            return [
                JSONResponse(
                    {
                        "error": "Coverage could not be created.",
                        "field_errors": _field_errors_from_pydantic(exc),
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [effect, JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED)]

    @api.post("/coverage/<coverage_id>")
    def update_coverage(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        body = self.request.json() or {}
        fields, err = _build_effect_fields(body)
        if err:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]
        try:
            effect = CoverageEffect(coverage_id=coverage_id, **fields).update()
        except PydanticValidationError as exc:
            return [
                JSONResponse(
                    {
                        "error": "Coverage could not be updated.",
                        "field_errors": _field_errors_from_pydantic(exc),
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [effect, JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED)]

    @api.post("/coverage/<coverage_id>/remove")
    def remove_coverage(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        return [
            CoverageEffect(coverage_id=coverage_id).remove(),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]

    @api.post("/coverage/<coverage_id>/expire")
    def expire_coverage(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
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
    def remove_photo(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        side = self.request.path_params.get("side") or ""
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

    # ---- ID cards ----

    @api.get("/id-cards.json")
    def id_cards_data(self) -> list[Response | Effect]:
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
        cards = (
            PatientIdentificationCard.objects.filter(patient=patient)
            .order_by("-created")
        )
        return [
            JSONResponse(
                {
                    "patient_id": str(patient.id),
                    "id_cards": [
                        {
                            "id": c.dbid,
                            "title": c.title or "",
                            "active": c.active,
                            "image_url": c.image_url,
                        }
                        for c in cards
                    ],
                }
            )
        ]

    @api.post("/id-card")
    def create_id_card(self) -> list[Response | Effect]:
        body = self.request.json() or {}
        patient_id = (body.get("patient_id") or "").strip()
        image_upload_key = body.get("image_upload_key")
        if not patient_id:
            return [
                JSONResponse(
                    {"error": "patient_id is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]
        if not image_upload_key:
            return [
                JSONResponse(
                    {
                        "error": "Image is required.",
                        "field_errors": {"image": "Image is required."},
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            effect = PatientIdentificationCardEffect(
                patient_id=patient_id,
                image_upload_key=image_upload_key,
                title=body.get("title") or "",
                active=body.get("active", True),
            ).create()
        except PydanticValidationError as exc:
            return [
                JSONResponse(
                    {
                        "error": "ID card could not be created.",
                        "field_errors": _field_errors_from_pydantic(exc),
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [effect, JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED)]

    @api.post("/id-card/<card_id>")
    def update_id_card(self) -> list[Response | Effect]:
        card_id = self.request.path_params.get("card_id") or ""
        body = self.request.json() or {}
        try:
            card_id_int = int(card_id)
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "card_id must be an integer"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        kwargs: dict[str, Any] = {"card_id": card_id_int}
        if "image_upload_key" in body and body["image_upload_key"]:
            kwargs["image_upload_key"] = body["image_upload_key"]
        if "title" in body and body["title"] is not None:
            kwargs["title"] = body["title"]
        if "active" in body and body["active"] is not None:
            kwargs["active"] = bool(body["active"])
        try:
            effect = PatientIdentificationCardEffect(**kwargs).update()
        except PydanticValidationError as exc:
            return [
                JSONResponse(
                    {
                        "error": "ID card could not be updated.",
                        "field_errors": _field_errors_from_pydantic(exc),
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [effect, JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED)]

    @api.post("/id-card/<card_id>/delete")
    def delete_id_card(self) -> list[Response | Effect]:
        card_id = self.request.path_params.get("card_id") or ""
        try:
            card_id_int = int(card_id)
        except (TypeError, ValueError):
            return [
                JSONResponse(
                    {"error": "card_id must be an integer"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [
            PatientIdentificationCardEffect(card_id=card_id_int).delete(),
            JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED),
        ]
