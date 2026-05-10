"""External bearer-authenticated API for setting patient tags programmatically.

Auth: Bearer token, validated against the `API_TOKEN` plugin secret. If the
secret is unset the API is closed (rejects all requests). Set the secret in
the Canvas instance plugin settings to enable.

Endpoints (all prefixed with `/api`):
  GET   /api/labels                          — list available labels
  GET   /api/patients/<id>/labels            — current assignments
  POST  /api/patients/<id>/labels            — replace assignments
  POST  /api/patients/<id>/labels/add        — add labels (idempotent, no-op for already assigned)
  POST  /api/patients/<id>/labels/remove     — remove labels (idempotent, no-op for not present)

POST bodies accept either `{"label_ids": [1, 2]}` (preferred) or
`{"labels": ["Banned", "VIP"]}` (resolved by name).

Audit entries from this API are attributed to actor "API" so the history
view can distinguish programmatic changes from staff actions.
"""
from hmac import compare_digest
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import BearerCredentials

from patient_tags.models import Label, PatientProxy
from patient_tags.services.banner_service import compute_banner_effects
from patient_tags.services.label_service import (
    add_patient_assignments,
    get_patient_assignment_ids,
    list_labels,
    remove_patient_assignments,
    save_patient_assignments,
)

API_TOKEN_SECRET = "API_TOKEN"


def _resolve_label_ids(body: dict[str, Any]) -> tuple[list[int] | None, str | None]:
    """Resolve a request body into a list of label IDs.

    Returns (label_ids, error). Exactly one of the two will be non-None.
    Accepts either `label_ids` (list of ints) or `labels` (list of names).
    """
    if body.get("label_ids") is not None:
        try:
            return [int(x) for x in body["label_ids"]], None
        except (TypeError, ValueError):
            return None, "label_ids must be a list of integers."
    if body.get("labels") is not None:
        names = body["labels"]
        if not isinstance(names, list):
            return None, "labels must be a list of label names."
        resolved = dict(
            Label.objects.filter(name__in=names).values_list("name", "dbid")
        )
        unknown = [n for n in names if n not in resolved]
        if unknown:
            return None, f"Unknown labels: {unknown}"
        return [resolved[n] for n in names], None
    return None, "Body must include either 'label_ids' or 'labels'."


class TagExternalAPI(SimpleAPI):
    """Bearer-token-authenticated API for assigning patient tags from external systems."""

    PREFIX = "/api"

    def authenticate(self, credentials: BearerCredentials) -> bool:
        expected = self.secrets.get(API_TOKEN_SECRET, "")
        if not expected:
            return False
        return compare_digest(credentials.token, expected)

    @api.get("/labels")
    def get_labels(self) -> list[Response | Effect]:
        return [JSONResponse({"labels": list_labels()})]

    @api.get("/patients/<patient_id>/labels")
    def get_patient_labels(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        return [JSONResponse({"label_ids": get_patient_assignment_ids(patient_id)})]

    @api.post("/patients/<patient_id>/labels")
    def replace_patient_labels(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        ids, err = _resolve_label_ids(self.request.json())
        if err:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]
        try:
            save_patient_assignments(patient_id, ids or [], actor_id="", actor_name="API")
        except PatientProxy.DoesNotExist:
            return [JSONResponse(
                {"error": f"Patient {patient_id!r} not found."},
                status_code=HTTPStatus.NOT_FOUND,
            )]
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        effects = compute_banner_effects(patient_id)
        return [JSONResponse(
            {"status": "ok", "label_ids": get_patient_assignment_ids(patient_id)}
        )] + effects

    @api.post("/patients/<patient_id>/labels/add")
    def add_patient_labels(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        ids, err = _resolve_label_ids(self.request.json())
        if err:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]
        try:
            result = add_patient_assignments(patient_id, ids or [], actor_id="", actor_name="API")
        except PatientProxy.DoesNotExist:
            return [JSONResponse(
                {"error": f"Patient {patient_id!r} not found."},
                status_code=HTTPStatus.NOT_FOUND,
            )]
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        effects = compute_banner_effects(patient_id)
        return [JSONResponse({
            "status": "ok",
            "added": result["added"],
            "already_present": result["already_present"],
            "label_ids": get_patient_assignment_ids(patient_id),
        })] + effects

    @api.post("/patients/<patient_id>/labels/remove")
    def remove_patient_labels(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        ids, err = _resolve_label_ids(self.request.json())
        if err:
            return [JSONResponse({"error": err}, status_code=HTTPStatus.BAD_REQUEST)]
        try:
            result = remove_patient_assignments(patient_id, ids or [], actor_id="", actor_name="API")
        except PatientProxy.DoesNotExist:
            return [JSONResponse(
                {"error": f"Patient {patient_id!r} not found."},
                status_code=HTTPStatus.NOT_FOUND,
            )]
        effects = compute_banner_effects(patient_id)
        return [JSONResponse({
            "status": "ok",
            "removed": result["removed"],
            "not_present": result["not_present"],
            "label_ids": get_patient_assignment_ids(patient_id),
        })] + effects
