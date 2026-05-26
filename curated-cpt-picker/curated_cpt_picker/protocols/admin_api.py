from datetime import date
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import ChargeDescriptionMaster

from curated_cpt_picker.models.curated_cpt_code import CuratedCptCode
from curated_cpt_picker.lib.admin_auth import is_admin
from curated_cpt_picker.lib.cdm_validation import _is_usable, validate_cpt_code


def _serialize(entry: CuratedCptCode) -> dict:
    return {
        "id": str(entry.pk),
        "cpt_code": entry.cpt_code,
        "description": entry.description,
        "default_units": entry.default_units,
        "modifiers": entry.modifiers or [],
        "display_order": entry.display_order,
        "enabled": entry.enabled,
    }


def _forbidden() -> list[Response | Effect]:
    return [JSONResponse({"error": "Forbidden"}, status_code=HTTPStatus.FORBIDDEN)]


class AdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """CRUD + UI for the curated CPT list.

    StaffSessionAuthMixin proves the request is from a logged-in staff
    member. The ADMIN_STAFF_IDS check below adds an optional second gate
    that the deploying admin can opt into (default is permissive — see
    lib/admin_auth.py).
    """

    def _current_staff_id(self) -> str | None:
        return self.request.headers.get("canvas-logged-in-user-id")

    def _check_admin(self) -> bool:
        return is_admin(self._current_staff_id(), self.secrets.get("ADMIN_STAFF_IDS", ""))

    @api.get("/admin")
    def render_admin(self) -> list[Response | Effect]:
        if not self._check_admin():
            return [HTMLResponse("<p>Forbidden — your account does not have access to the curated CPT admin.</p>", status_code=HTTPStatus.FORBIDDEN)]

        entries = [_serialize(e) for e in CuratedCptCode.objects.all().order_by("display_order", "cpt_code")]
        html = render_to_string("templates/admin_app.html", {"entries": entries})
        return [HTMLResponse(html)]

    @api.get("/admin/codes")
    def list_codes(self) -> list[Response | Effect]:
        if not self._check_admin():
            return _forbidden()
        entries = [_serialize(e) for e in CuratedCptCode.objects.all().order_by("display_order", "cpt_code")]
        return [JSONResponse({"entries": entries})]

    @api.get("/admin/cdm-codes")
    def list_cdm_codes(self) -> list[Response | Effect]:
        """Return CDM rows currently active today, for the admin CPT dropdown."""
        if not self._check_admin():
            return _forbidden()

        today = date.today()
        rows = list(ChargeDescriptionMaster.objects.all().order_by("cpt_code"))
        seen: set[str] = set()
        cdm_codes = []
        for row in rows:
            # Filter on _is_usable (not just _is_currently_active) so the
            # dropdown hides codes whose description would exceed Canvas's
            # 255-char BillingLineItem.description limit — those would pass
            # admin validation but fail later when AddBillingLineItem fires.
            if row.cpt_code in seen or not _is_usable(row, today):
                continue
            seen.add(row.cpt_code)
            # short_name is meant for display; fall back to name when short_name is empty
            label = (row.short_name or row.name or "").strip()
            cdm_codes.append({"cpt_code": row.cpt_code, "label": label})
        return [JSONResponse({"cdm_codes": cdm_codes})]

    @api.post("/admin/codes")
    def create_code(self) -> list[Response | Effect]:
        if not self._check_admin():
            return _forbidden()

        body = self.request.json()
        cpt_code = (body.get("cpt_code") or "").strip()
        description = (body.get("description") or "").strip()
        if not cpt_code or not description:
            return [JSONResponse({"error": "cpt_code and description are required"}, status_code=HTTPStatus.BAD_REQUEST)]

        validation = validate_cpt_code(cpt_code)
        if not validation.is_valid:
            return [JSONResponse({"error": validation.reason}, status_code=HTTPStatus.UNPROCESSABLE_ENTITY)]

        entry = CuratedCptCode.objects.create(
            cpt_code=cpt_code,
            description=description,
            default_units=body.get("default_units") or 1,
            modifiers=body.get("modifiers") or [],
            display_order=body.get("display_order") or 0,
            enabled=body.get("enabled", True),
        )
        return [JSONResponse(_serialize(entry), status_code=HTTPStatus.CREATED)]

    @api.patch("/admin/codes/<entry_id>")
    def update_code(self) -> list[Response | Effect]:
        if not self._check_admin():
            return _forbidden()

        entry_id = self.request.path_params["entry_id"]
        try:
            entry = CuratedCptCode.objects.get(pk=entry_id)
        except (CuratedCptCode.DoesNotExist, ValueError):
            return [JSONResponse({"error": "Not found"}, status_code=HTTPStatus.NOT_FOUND)]

        body = self.request.json()

        new_cpt = body.get("cpt_code")
        if new_cpt is not None and new_cpt.strip() and new_cpt.strip() != entry.cpt_code:
            validation = validate_cpt_code(new_cpt.strip())
            if not validation.is_valid:
                return [JSONResponse({"error": validation.reason}, status_code=HTTPStatus.UNPROCESSABLE_ENTITY)]
            entry.cpt_code = new_cpt.strip()

        if "description" in body:
            entry.description = (body["description"] or "").strip() or entry.description
        if "default_units" in body and body["default_units"]:
            entry.default_units = int(body["default_units"])
        if "modifiers" in body:
            entry.modifiers = body["modifiers"] or []
        if "display_order" in body and body["display_order"] is not None:
            entry.display_order = int(body["display_order"])
        if "enabled" in body:
            entry.enabled = bool(body["enabled"])

        entry.save()
        return [JSONResponse(_serialize(entry))]

    @api.delete("/admin/codes/<entry_id>")
    def delete_code(self) -> list[Response | Effect]:
        if not self._check_admin():
            return _forbidden()

        entry_id = self.request.path_params["entry_id"]
        try:
            deleted, _ = CuratedCptCode.objects.filter(pk=entry_id).delete()
        except ValueError:
            return [JSONResponse({"error": "Not found"}, status_code=HTTPStatus.NOT_FOUND)]
        if not deleted:
            return [JSONResponse({"error": "Not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"deleted": entry_id})]
