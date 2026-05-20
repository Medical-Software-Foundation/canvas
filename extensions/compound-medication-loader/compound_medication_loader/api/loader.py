"""
SimpleAPI: Bulk-load Compound Medications into a Canvas instance.

Routes (mounted under /plugin-io/api/compound_medication_loader):
  GET  /enums                   List valid potency_unit_code and controlled_substance values
  GET  /existing                Map of {formulation: active} for every compound already in the instance
  GET  /ping                    Liveness check — always 200 if plugin is loaded and authenticated
  POST /compound-medications    Create compounds from a JSON payload

Auth: Authorization: Bearer <BULK_LOAD_API_KEY> (per-instance secret).

POST /compound-medications request body:
  {
    "skip_existing": true,           # optional, default true; skip rows whose
                                     # formulation already exists in the DB
    "compounds": [
      {
        "formulation": "Lidocaine 2% / Prilocaine 2.5% topical cream",
        "potency_unit_code": "C48155",
        "controlled_substance": "N",
        "controlled_substance_ndc": null,
        "active": true
      },
      ...
    ]
  }

Response:
  {
    "summary": {"total": N, "created": X, "skipped": Y, "errors": Z},
    "results": [
      {"index": 0, "formulation": "...", "already_exists": false, "existing_active": null, "status": "created"},
      {"index": 1, "formulation": "...", "already_exists": true,  "existing_active": true,  "status": "skipped", "reason": "..."},
      {"index": 2, "formulation": "...", "already_exists": true,  "existing_active": false, "status": "error",   "errors": ["..."]},
      ...
    ]
  }

Every result row carries `already_exists` and `existing_active` regardless of
the `skip_existing` setting, so callers can show dedup status in their own UI
even when they choose to attempt the create.
"""

# `from __future__ import annotations` is REQUIRED here. The plugin runner uses
# RestrictedPython, which evaluates annotations at def time and silently fails
# the plugin load when module-level functions use PEP 585 generic aliases like
# `set[str]` or `dict[str, Any]` in their signatures. Lazy annotations sidestep
# this entirely. See `reference_canvas_sdk_gotchas.md`.
from __future__ import annotations

import hmac
import json
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from canvas_sdk.v1.data.compound_medication import (
    CompoundMedication as CompoundMedicationModel,
)
from logger import log

MAX_FORMULATION_LEN = 105
NOT_SCHEDULED = "N"


def _potency_unit_choices() -> list[tuple[str, str]]:
    return list(CompoundMedicationModel.PotencyUnits.choices)


def _controlled_substance_choices() -> list[tuple[str, str]]:
    return list(CompoundMedicationModel.ControlledSubstanceOptions.choices)


class CompoundMedicationLoaderAPI(SimpleAPI):
    PREFIX = None

    def authenticate(self, credentials: Credentials) -> bool:
        # Path 1: Canvas staff session (when called from the app-drawer modal).
        # Canvas sets these headers only for valid logged-in sessions; clients
        # cannot spoof them.
        if self.request.headers.get("canvas-logged-in-user-type") == "Staff":
            return True

        # Path 2: Bearer token (programmatic CLI/script use). Constant-time
        # compare prevents leaking the secret via response-time differences,
        # matching the repo-wide convention (patient_tags, sticky_note,
        # nutrition_charting, extend_lab_intake).
        expected = (self.secrets.get("BULK_LOAD_API_KEY") or "").strip()
        if not expected:
            return False
        provided = self.request.headers.get("Authorization", "")
        return hmac.compare_digest(provided, f"Bearer {expected}")

    @api.get("/ping")
    def ping(self) -> list[Response | Effect]:
        return [JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    @api.get("/existing")
    def existing(self) -> list[Response | Effect]:
        """Map of `formulation -> active` for every compound already in the
        instance, so the review UI can flag duplicates before submission."""
        pairs = CompoundMedicationModel.objects.values_list("formulation", "active")
        return [
            JSONResponse(
                {"compounds": {f: bool(a) for f, a in pairs}},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/enums")
    def enums(self) -> list[Response | Effect]:
        return [
            JSONResponse(
                {
                    "potency_unit_code": [
                        {"code": code, "label": label}
                        for code, label in _potency_unit_choices()
                    ],
                    "controlled_substance": [
                        {"code": code, "label": label}
                        for code, label in _controlled_substance_choices()
                    ],
                    "max_formulation_length": MAX_FORMULATION_LEN,
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/compound-medications")
    def bulk_create(self) -> list[Response | Effect]:
        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            return [
                JSONResponse(
                    {"error": "Invalid JSON body."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        if not isinstance(body, dict):
            return [
                JSONResponse(
                    {"error": "Body must be a JSON object."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        rows = body.get("compounds")
        if not isinstance(rows, list) or not rows:
            return [
                JSONResponse(
                    {"error": "Expected non-empty list under 'compounds' key."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        skip_existing = bool(body.get("skip_existing", True))
        # Always load the existing-compound index so every result row can
        # report `already_exists` regardless of skip behavior.
        existing_compounds: dict[str, bool] = dict(
            CompoundMedicationModel.objects.values_list("formulation", "active")
        )

        valid_potency = {code for code, _ in _potency_unit_choices()}
        valid_controlled = {code for code, _ in _controlled_substance_choices()}

        results: list[dict] = []
        effects: list[Effect] = []

        for idx, row in enumerate(rows):
            row_result = _process_row(
                row,
                idx,
                existing_compounds,
                skip_existing,
                valid_potency,
                valid_controlled,
            )
            if row_result["status"] == "created":
                effects.append(row_result.pop("_effect"))
            results.append(row_result)

        summary = {
            "total": len(rows),
            "created": sum(1 for r in results if r["status"] == "created"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "errors": sum(1 for r in results if r["status"] == "error"),
        }
        log.info(f"[compound_medication_loader] bulk load summary: {summary}")

        return [
            JSONResponse(
                {"summary": summary, "results": results},
                status_code=HTTPStatus.OK,
            ),
            *effects,
        ]


def _process_row(
    row: object,
    idx: int,
    existing_compounds: dict[str, bool],
    skip_existing: bool,
    valid_potency: set[str],
    valid_controlled: set[str],
) -> dict:
    if not isinstance(row, dict):
        return {
            "index": idx,
            "formulation": None,
            "already_exists": False,
            "existing_active": None,
            "status": "error",
            "errors": ["row must be a JSON object"],
        }

    formulation = (row.get("formulation") or "").strip()
    potency_unit_code = row.get("potency_unit_code")
    # Don't default controlled_substance — a missing/blank value must surface
    # as a validation error rather than silently classifying as "Not scheduled".
    # Loading a Schedule II compound as uncontrolled would have real prescribing
    # / DEA-compliance consequences.
    raw_controlled = row.get("controlled_substance")
    controlled_substance = (
        str(raw_controlled).strip() if raw_controlled is not None else ""
    )
    controlled_substance_ndc = (row.get("controlled_substance_ndc") or "").strip() or None
    active = row.get("active", True)

    existing_active = existing_compounds.get(formulation) if formulation else None
    already_exists = existing_active is not None

    errors = _validate_row(
        formulation,
        potency_unit_code,
        controlled_substance,
        controlled_substance_ndc,
        valid_potency,
        valid_controlled,
    )
    if errors:
        return {
            "index": idx,
            "formulation": formulation or None,
            "already_exists": already_exists,
            "existing_active": existing_active,
            "status": "error",
            "errors": errors,
        }

    if skip_existing and already_exists:
        return {
            "index": idx,
            "formulation": formulation,
            "already_exists": True,
            "existing_active": existing_active,
            "status": "skipped",
            "reason": (
                "formulation already exists (active)"
                if existing_active
                else "formulation already exists (inactive)"
            ),
        }

    # Emit the raw Effect with a flat payload rather than going through
    # `CompoundMedication(...).create()`. The SDK helper wraps fields under
    # a "data" key, but the server-side CREATE_COMPOUND_MEDICATION
    # interpreter validates against a flat schema and reports every field
    # as "required" when nested. Confirmed working end-to-end on
    # plugin-testing.
    payload: dict = {
        "formulation": formulation,
        "potency_unit_code": potency_unit_code,
        "controlled_substance": controlled_substance,
        "active": active,
    }
    if controlled_substance_ndc:
        payload["controlled_substance_ndc"] = controlled_substance_ndc.replace("-", "")
    # Effect() is internal pydantic construction over already-validated data
    # — any failure here is a real bug that should propagate to Canvas logs
    # and Sentry, not be silently flattened to a per-row error.
    effect = Effect(
        type="CREATE_COMPOUND_MEDICATION",
        payload=json.dumps(payload),
    )

    existing_compounds[formulation] = bool(active)

    return {
        "index": idx,
        "formulation": formulation,
        "already_exists": already_exists,
        "existing_active": existing_active,
        "status": "created",
        "_effect": effect,
    }


def _validate_row(
    formulation: str,
    potency_unit_code: object,
    controlled_substance: object,
    controlled_substance_ndc: str | None,
    valid_potency: set[str],
    valid_controlled: set[str],
) -> list[str]:
    errors: list[str] = []
    if not formulation:
        errors.append("formulation is required")
    elif len(formulation) > MAX_FORMULATION_LEN:
        errors.append(f"formulation must be <= {MAX_FORMULATION_LEN} characters")

    if not potency_unit_code:
        errors.append("potency_unit_code is required (see GET /enums)")
    elif potency_unit_code not in valid_potency:
        errors.append(
            f"invalid potency_unit_code {potency_unit_code!r} (see GET /enums)"
        )

    if not controlled_substance:
        errors.append(
            "controlled_substance is required (see GET /enums; use 'N' for Not scheduled)"
        )
    elif controlled_substance not in valid_controlled:
        errors.append(
            f"invalid controlled_substance {controlled_substance!r} (see GET /enums)"
        )
    elif controlled_substance != NOT_SCHEDULED and not controlled_substance_ndc:
        errors.append(
            f"controlled_substance_ndc is required when controlled_substance != {NOT_SCHEDULED!r}"
        )

    return errors
