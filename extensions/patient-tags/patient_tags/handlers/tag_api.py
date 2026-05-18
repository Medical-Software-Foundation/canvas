from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from canvas_sdk.v1.data import Staff
from canvas_sdk.v1.data.staff import StaffRole

MANAGE_TABS_ROLES_SECRET = "MANAGE_TABS_ROLES"


def _allowed_role_codes(secrets: dict) -> set[str]:
    """Parse the comma-separated MANAGE_TABS_ROLES secret. Empty → no restriction."""
    raw = str(secrets.get(MANAGE_TABS_ROLES_SECRET, "")).strip()
    if not raw:
        return set()
    return {code.strip() for code in raw.split(",") if code.strip()}


def _can_manage(staff_uuid: str, secrets: dict) -> bool:
    """True if the given user may see Manage Labels / Manage Banners tabs.

    Empty / unset secret → all users allowed (current behavior). Otherwise
    user must have at least one role with `internal_code` in the secret list.
    """
    allowed = _allowed_role_codes(secrets)
    if not allowed:
        return True
    if not staff_uuid:
        return False
    user_codes = set(
        StaffRole.objects
        .filter(staff__id=staff_uuid)
        .values_list("internal_code", flat=True)
    )
    return bool(user_codes & allowed)

from patient_tags.services.banner_service import compute_banner_effects
from patient_tags.services.label_service import (
    create_banner_group,
    create_label,
    create_rule,
    delete_banner_group,
    delete_label,
    delete_rule,
    get_patient_assignment_ids,
    list_banner_groups,
    list_labels,
    list_patient_history,
    list_rules_for_label,
    save_patient_assignments,
    update_banner_group,
    update_label,
)


def _resolve_actor(staff_uuid: str) -> tuple[str, str]:
    """Look up a staff display name. Returns (id, name) or (id, '') on miss."""
    if not staff_uuid:
        return ("", "")
    row = Staff.objects.filter(id=staff_uuid).values_list("first_name", "last_name").first()
    if not row:
        return (staff_uuid, "")
    first, last = row
    name = f"{first or ''} {last or ''}".strip()
    return (staff_uuid, name or "")


class TagAPI(StaffSessionAuthMixin, SimpleAPI):
    """REST endpoints for managing labels, banner groups, and patient assignments."""

    PREFIX = ""

    @api.get("/labels")
    def get_labels(self) -> list[Response | Effect]:
        return [JSONResponse({"labels": list_labels()})]

    @api.post("/labels")
    def post_label(self) -> list[Response | Effect]:
        body = self.request.json()
        try:
            label = create_label(
                name=body.get("name", ""),
                description=body.get("description", ""),
                color=body.get("color", "blue"),
                assignable_in_chart=body.get("assignable_in_chart", True),
                assignable_in_profile=body.get("assignable_in_profile", True),
                banner_group_id=body.get("banner_group_id"),
            )
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(label, status_code=HTTPStatus.CREATED)]

    @api.patch("/labels/<label_id>")
    def patch_label(self) -> list[Response | Effect]:
        label_id = int(self.request.path_params["label_id"])
        body = self.request.json()
        try:
            label, effects = update_label(label_id, **body)
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(label)] + effects

    @api.delete("/labels/<label_id>")
    def remove_label(self) -> list[Response | Effect]:
        label_id = int(self.request.path_params["label_id"])
        effects = delete_label(label_id)
        return [JSONResponse({"status": "ok"})] + effects

    @api.get("/banner-groups")
    def get_banner_groups(self) -> list[Response | Effect]:
        return [JSONResponse({"groups": list_banner_groups()})]

    @api.post("/banner-groups")
    def post_banner_group(self) -> list[Response | Effect]:
        body = self.request.json()
        try:
            group = create_banner_group(
                name=body.get("name", ""),
                intent=body.get("intent", "info"),
                placements=body.get("placements") or ["CHART"],
                separator=body.get("separator", " • "),
                href=body.get("href", ""),
            )
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(group, status_code=HTTPStatus.CREATED)]

    @api.patch("/banner-groups/<group_id>")
    def patch_banner_group(self) -> list[Response | Effect]:
        group_id = int(self.request.path_params["group_id"])
        body = self.request.json()
        try:
            group = update_banner_group(group_id, **body)
        except ValueError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(group)]

    @api.delete("/banner-groups/<group_id>")
    def remove_banner_group(self) -> list[Response | Effect]:
        group_id = int(self.request.path_params["group_id"])
        effects = delete_banner_group(group_id)
        return [JSONResponse({"status": "ok"})] + effects

    @api.get("/me/can-manage")
    def get_me_can_manage(self) -> list[Response | Effect]:
        staff_uuid = self.request.headers.get("canvas-logged-in-user-id", "")
        return [JSONResponse({"can_manage": _can_manage(staff_uuid, self.secrets)})]

    @api.get("/labels/<label_id>/rules")
    def get_label_rules(self) -> list[Response | Effect]:
        label_id = int(self.request.path_params["label_id"])
        return [JSONResponse({"rules": list_rules_for_label(label_id)})]

    @api.post("/labels/<label_id>/rules")
    def post_label_rule(self) -> list[Response | Effect]:
        trigger_label_id = int(self.request.path_params["label_id"])
        body = self.request.json()
        try:
            rule = create_rule(
                trigger_label_id=trigger_label_id,
                action=body.get("action", ""),
                target_label_id=int(body.get("target_label_id", 0)),
            )
        except (ValueError, TypeError) as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(rule, status_code=HTTPStatus.CREATED)]

    @api.delete("/rules/<rule_id>")
    def remove_rule(self) -> list[Response | Effect]:
        rule_id = int(self.request.path_params["rule_id"])
        delete_rule(rule_id)
        return [JSONResponse({"status": "ok"})]

    @api.get("/patients/<patient_id>/labels")
    def get_patient_labels(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        return [JSONResponse({"label_ids": get_patient_assignment_ids(patient_id)})]

    @api.post("/patients/<patient_id>/labels")
    def save_patient_labels(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        body = self.request.json()
        label_ids = [int(x) for x in body.get("label_ids", [])]
        actor_id, actor_name = _resolve_actor(
            self.request.headers.get("canvas-logged-in-user-id", "")
        )
        save_patient_assignments(patient_id, label_ids, actor_id=actor_id, actor_name=actor_name)
        effects = compute_banner_effects(patient_id)
        return [JSONResponse({"status": "ok"})] + effects

    @api.get("/patients/<patient_id>/labels/history")
    def get_patient_history(self) -> list[Response | Effect]:
        patient_id = self.request.path_params["patient_id"]
        return [JSONResponse({"history": list_patient_history(patient_id)})]
