"""SimpleAPI for the patient-coverage companion.

Endpoints (all under /plugin-io/api/patient_coverage_companion/app/):

| GET  /                                    | HTML shell                       |
| GET  /main.js                             | JS bundle                        |
| GET  /styles.css                          | CSS                              |
| GET  /data.json?patient_id=X              | Coverages list + dropdowns       |
| GET  /payers/search?q=Y                   | Transactor type-ahead            |
| POST /cards/upload  (file_uploads=stored) | Card photo uploads -> upload keys|
| POST /coverage                            | Create — Coverage(...).create()  |
| POST /coverage/<id>                       | Update — Coverage(...).update()  |
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

import re
from datetime import UTC, date, datetime
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.coverage import Coverage as CoverageEffect
from canvas_sdk.effects.coverage import CoverageReorder, PhotoSide
from canvas_sdk.effects.patient import (
    PatientIdentificationCard as PatientIdentificationCardEffect,
)
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SimpleAPI,
    StaffSessionAuthMixin,
    StoredFilePart,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.coverage import (
    Coverage,
    CoverageRank,
    CoverageRelationshipCode,
    CoverageStack,
    Transactor,
)
from canvas_sdk.v1.data.patient import Patient, PatientIdentificationCard
from pydantic import ValidationError as PydanticValidationError

_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))

_RELATIONSHIP_CHOICES = [
    {"value": value, "label": label}
    for value, label in CoverageRelationshipCode.choices
]
_RANK_CHOICES = [
    {"value": int(value), "label": label} for value, label in CoverageRank.choices
]

# Fields the user must supply to create a new coverage. Mirrors the SDK's
# Coverage create checks; surfacing them here lets us return a structured
# field-level 400 with friendly labels before invoking the SDK. Plan type is
# not here: it follows the payer and is not writable through the effect.
_CREATE_REQUIRED_FIELDS = {
    "issuer_id": "Payer",
    "id_number": "Member ID",
    "coverage_rank": "Rank",
    "patient_relationship_to_subscriber": "Relationship to subscriber",
}

# The SDK's effect validators raise errors without a pydantic ``loc``; they
# name the field in the message instead ("Field 'coverage_rank' ...").
_FIELD_IN_MESSAGE = re.compile(r"Field '(\w+)'")
# SDK messages that name no field: the create-time rank check and the
# start-before-end date check.
_RANK_CONFLICT_MESSAGE = re.compile(r"already has an active \w+ coverage with rank")
_DATE_ORDER_MESSAGE = re.compile(r"start date must be on or before its end date")
_DATE_FORMAT_MESSAGE = "Enter the date as YYYY-MM-DD, for example 2026-12-31."


def _field_errors_from_pydantic(exc: PydanticValidationError) -> dict[str, str]:
    """Map a pydantic ValidationError into a {field_name: message} dict.

    Plain pydantic errors carry the field in ``loc``. The SDK's own write
    checks carry no ``loc`` and name the field in the message, so we parse
    that. Anything else falls back to the generic ``__form__`` key.
    """
    field_errors: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc") or ()
        msg = err.get("msg") or "invalid"
        if loc:
            key = str(loc[0])
        elif match := _FIELD_IN_MESSAGE.search(msg):
            key = match.group(1)
        elif _RANK_CONFLICT_MESSAGE.search(msg):
            key = "coverage_rank"
        elif _DATE_ORDER_MESSAGE.search(msg):
            key = "coverage_end_date"
        else:
            key = "__form__"
        # First error wins per field; collapse duplicates from nested rules.
        field_errors.setdefault(key, msg)
    return field_errors


def _validation_error_response(
    message: str, exc: PydanticValidationError
) -> JSONResponse:
    """A 400 carrying a summary and per-field errors from an effect's validation."""
    return JSONResponse(
        {"error": message, "field_errors": _field_errors_from_pydantic(exc)},
        status_code=HTTPStatus.BAD_REQUEST,
    )


def _first_message(exc: PydanticValidationError, fallback: str) -> str:
    """The first human-readable reason in an effect's validation error."""
    errors = exc.errors()
    return (errors[0].get("msg") if errors else None) or fallback


def _end_date_error(message: str) -> JSONResponse:
    return JSONResponse(
        {"error": message, "field_errors": {"coverage_end_date": message}},
        status_code=HTTPStatus.BAD_REQUEST,
    )


def _submitted() -> JSONResponse:
    return JSONResponse({"status": "submitted"}, status_code=HTTPStatus.ACCEPTED)


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
        # The effect takes the payer's UUID ``id``; ``issuer_id`` is the
        # numeric FK column, so read through the relation.
        "issuer_id": str(coverage.issuer.id) if coverage.issuer_id else None,
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


def _build_effect_fields(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Translate a request body into kwargs for ``CoverageEffect(...)``.

    Returns (kwargs, field_errors). ``field_errors`` maps a field name to a
    plain-language message the form shows inline. Empty / null fields are
    dropped so the update path doesn't clobber unset fields.
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
    errors: dict[str, str] = {}
    rank: Any = body.get("coverage_rank")
    if rank not in (None, ""):
        try:
            out["coverage_rank"] = int(rank)
        except (TypeError, ValueError):
            errors["coverage_rank"] = "Rank must be a whole number."
    stack = body.get("stack")
    if stack:
        if stack not in {s.value for s in CoverageStack}:
            allowed = ", ".join(sorted(s.value for s in CoverageStack))
            errors["stack"] = f"Stack must be one of {allowed}."
        else:
            out["stack"] = stack
    for field in ("coverage_start_date", "coverage_end_date"):
        try:
            parsed = _parse_date(body.get(field))
        except (TypeError, ValueError):
            # Don't echo Python's parse error ("Invalid isoformat string").
            errors[field] = _DATE_FORMAT_MESSAGE
            continue
        if parsed is not None:
            out[field] = parsed
    if errors:
        return {}, errors
    return out, None


def _field_errors_response(field_errors: dict[str, str]) -> JSONResponse:
    """A 400 whose summary is the first field's message, shown in the banner."""
    return JSONResponse(
        {"error": next(iter(field_errors.values())), "field_errors": field_errors},
        status_code=HTTPStatus.BAD_REQUEST,
    )


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
            return [
                JSONResponse(
                    {"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]

        coverages = (
            Coverage.objects.filter(patient=patient)
            .exclude(stack="REMOVED")
            .select_related("issuer", "subscriber", "snapshot")
            # _serialize_coverage reads snapshot.images per coverage.
            .prefetch_related("snapshot__images")
            .order_by("stack", "coverage_rank")
        )
        return [
            JSONResponse(
                {
                    "patient_id": str(patient.id),
                    "coverages": [_serialize_coverage(c) for c in coverages],
                    "options": {
                        "relationship": _RELATIONSHIP_CHOICES,
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
        # Coverage(issuer_id=...) takes the Transactor's UUID ``id``, not dbid.
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

    @api.post("/cards/upload", file_uploads="stored")
    def upload_cards(self) -> list[Response | Effect]:
        """Accept any named file parts; return the upload keys to the browser
        so the next save call can attach them via an effect. Used by both the
        Coverage flow (``front`` / ``back``) and the ID card flow (``image``).

        Canvas stores the files before this runs; each file part is a
        ``StoredFilePart`` carrying either ``key`` or ``error``.
        """
        form = self.request.form_data()
        keys: dict[str, str] = {}
        failures: dict[str, str] = {}
        for name, part in form.multi_items():
            if not isinstance(part, StoredFilePart):
                continue
            if part.error:
                failures[name] = part.error
            elif part.key:
                keys[name] = part.key
        if failures:
            # Don't hand back a partial set: the browser would save a coverage
            # with only one side attached and no hint the other side failed.
            return [
                JSONResponse(
                    {"error": "Card photo upload failed.", "failures": failures},
                    status_code=HTTPStatus.BAD_GATEWAY,
                )
            ]
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
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        fields, err = _build_effect_fields(body)
        if err:
            return [_field_errors_response(err)]

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

        # The SDK validates synchronously on .create(): payer exists, rank is
        # free among active coverages, subscriber rules, upload keys. Its
        # errors come back here as field-level 400s instead of an async
        # interpreter rejection after the browser already saw "Saved."
        try:
            effect = CoverageEffect(patient_id=patient_id, **fields).create()
        except PydanticValidationError as exc:
            return [_validation_error_response("Coverage could not be created.", exc)]
        return [effect, _submitted()]

    @api.post("/coverage/<coverage_id>")
    def update_coverage(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        body = self.request.json() or {}
        fields, err = _build_effect_fields(body)
        if err:
            return [_field_errors_response(err)]
        try:
            effect = CoverageEffect(coverage_id=coverage_id, **fields).update()
        except PydanticValidationError as exc:
            return [_validation_error_response("Coverage could not be updated.", exc)]
        return [effect, _submitted()]

    @api.post("/coverage/<coverage_id>/remove")
    def remove_coverage(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        try:
            effect = CoverageEffect(coverage_id=coverage_id).remove()
        except PydanticValidationError as exc:
            return [_validation_error_response("Coverage could not be removed.", exc)]
        return [effect, _submitted()]

    @api.post("/coverage/<coverage_id>/expire")
    def expire_coverage(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        body = self.request.json() or {}
        try:
            end = _parse_date(body.get("coverage_end_date"))
        except (TypeError, ValueError):
            return [_end_date_error(_DATE_FORMAT_MESSAGE)]
        if end is None:
            return [_end_date_error("End date is required.")]
        try:
            effect = CoverageEffect(coverage_id=coverage_id).expire(
                coverage_end_date=end
            )
        except PydanticValidationError as exc:
            # Expire has a single input, so the SDK's own reason (e.g. the
            # end date falls before the start date) is the useful message.
            message = _first_message(exc, "Coverage could not be expired.")
            return [_validation_error_response(message, exc)]
        return [effect, _submitted()]

    @api.post("/coverage/<coverage_id>/photo/<side>/remove")
    def remove_photo(self) -> list[Response | Effect]:
        coverage_id = self.request.path_params.get("coverage_id") or ""
        side = (self.request.path_params.get("side") or "").upper()
        if side not in {s.value for s in PhotoSide}:
            return [
                JSONResponse(
                    {"error": "side must be 'front' or 'back'"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        try:
            effect = CoverageEffect(coverage_id=coverage_id).remove_photo(
                PhotoSide(side)
            )
        except PydanticValidationError as exc:
            return [_validation_error_response("Card photo could not be removed.", exc)]
        return [effect, _submitted()]

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
        try:
            effect = CoverageReorder(patient_id=patient_id, ordering=ordering).apply()
        except PydanticValidationError as exc:
            return [
                _validation_error_response("Coverages could not be reordered.", exc)
            ]
        return [effect, _submitted()]

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
            return [
                JSONResponse(
                    {"error": "patient not found"}, status_code=HTTPStatus.NOT_FOUND
                )
            ]
        cards = PatientIdentificationCard.objects.filter(patient=patient).order_by(
            "-created"
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
                    {"error": "patient_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
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
            return [_validation_error_response("ID card could not be created.", exc)]
        return [effect, _submitted()]

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
        if body.get("image_upload_key"):
            kwargs["image_upload_key"] = body["image_upload_key"]
        if "title" in body and body["title"] is not None:
            kwargs["title"] = body["title"]
        if "active" in body and body["active"] is not None:
            kwargs["active"] = bool(body["active"])
        try:
            effect = PatientIdentificationCardEffect(**kwargs).update()
        except PydanticValidationError as exc:
            return [_validation_error_response("ID card could not be updated.", exc)]
        return [effect, _submitted()]

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
        try:
            effect = PatientIdentificationCardEffect(card_id=card_id_int).delete()
        except PydanticValidationError as exc:
            return [_validation_error_response("ID card could not be deleted.", exc)]
        return [effect, _submitted()]
