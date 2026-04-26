from __future__ import annotations

import json
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string

from staff_directory.data.nucc_seeder import ensure_nucc_seed
from staff_directory.services.certifications import (
    create as cert_create,
    delete as cert_delete,
    serialize as cert_serialize,
    update as cert_update,
)
from staff_directory.services.education import (
    create as edu_create,
    delete as edu_delete,
    serialize as edu_serialize,
    update as edu_update,
)
from staff_directory.services.permissions import is_admin, parse_admin_role_codes
from staff_directory.services.profiles import (
    get_staff_by_user_header,
    get_staff_profile,
    list_staff as svc_list_staff,
)
from staff_directory.services.specialties import (
    SpecialtyError,
    create as spec_create,
    delete as spec_delete,
    serialize as spec_serialize,
    set_primary as spec_set_primary,
)
from staff_directory.services.training import (
    create as train_create,
    delete as train_delete,
    serialize as train_serialize,
    update as train_update,
)


class StaffProfileAPI(StaffSessionAuthMixin, SimpleAPI):
    """Directory HTML and CRUD endpoints for staff profile entries."""

    PREFIX = "/app"

    def _current_staff(self):
        user_id = self.request.headers.get("canvas-logged-in-user-id", "")
        return get_staff_by_user_header(user_id)

    def _admin_codes(self) -> tuple[str, ...]:
        return parse_admin_role_codes(self.secrets.get("ADMIN_ROLE_CODES", ""))

    def _is_admin(self) -> bool:
        return is_admin(self._current_staff(), self._admin_codes())

    def _require_admin(self):
        if not self._is_admin():
            return JSONResponse(
                {"error": "Admin role required for this action."},
                status_code=HTTPStatus.FORBIDDEN,
            )
        return None

    @api.get("/directory")
    def get_directory(self) -> list[Response | Effect]:
        """Render the staff directory HTML used by the Application modal."""
        ensure_nucc_seed()

        staff_list = svc_list_staff()
        html = render_to_string(
            "templates/directory.html",
            {
                "staff_json": json.dumps(staff_list),
                "is_admin": json.dumps(self._is_admin()),
                "api_base": "/plugin-io/api/staff_directory/app",
                "nucc_base": "/plugin-io/api/staff_directory/nucc",
            },
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        css = render_to_string("static/css/styles.css")
        return [
            Response(
                css.encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/directory.js")
    def get_js(self) -> list[Response | Effect]:
        js = render_to_string("static/js/directory.js")
        return [
            Response(
                js.encode(),
                status_code=HTTPStatus.OK,
                content_type="application/javascript",
                headers={"Cache-Control": "no-cache"},
            )
        ]

    @api.get("/staff/")
    def list_staff(self) -> list[Response | Effect]:
        params = self.request.query_params
        search = params.get("search", "")
        specialty_code = params.get("specialty_code", "")
        expiring_within = params.get("expiring_within_days")
        expiring_within_days = int(expiring_within) if expiring_within else None

        data = svc_list_staff(
            search=search,
            specialty_code=specialty_code,
            expiring_within_days=expiring_within_days,
        )
        return [
            JSONResponse(
                {
                    "staff": data,
                    "count": len(data),
                    "is_admin": self._is_admin(),
                }
            )
        ]

    @api.get("/staff/<staff_dbid>/")
    def get_staff(self) -> list[Response | Effect]:
        staff_dbid = _parse_int(self.request.path_params.get("staff_dbid"))
        if staff_dbid is None:
            return [JSONResponse({"error": "Invalid staff id"}, status_code=HTTPStatus.BAD_REQUEST)]

        profile = get_staff_profile(staff_dbid)
        if profile is None:
            return [
                JSONResponse({"error": "Staff member not found"}, status_code=HTTPStatus.NOT_FOUND)
            ]
        profile["is_admin"] = self._is_admin()
        return [JSONResponse(profile)]

    # ----- Education -----

    @api.post("/staff/<staff_dbid>/education/")
    def add_education(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        staff_dbid = _parse_int(self.request.path_params.get("staff_dbid"))
        body = self.request.json() or {}
        entry = edu_create(staff_dbid, body)
        return [JSONResponse(edu_serialize(entry), status_code=HTTPStatus.CREATED)]

    @api.patch("/staff/<staff_dbid>/education/<entry_id>/")
    def update_education(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        body = self.request.json() or {}
        entry = edu_update(entry_id, body)
        if entry is None:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(edu_serialize(entry))]

    @api.delete("/staff/<staff_dbid>/education/<entry_id>/")
    def delete_education(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        ok = edu_delete(entry_id)
        if not ok:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"deleted": True})]

    # ----- Training -----

    @api.post("/staff/<staff_dbid>/training/")
    def add_training(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        staff_dbid = _parse_int(self.request.path_params.get("staff_dbid"))
        body = self.request.json() or {}
        entry = train_create(staff_dbid, body)
        return [JSONResponse(train_serialize(entry), status_code=HTTPStatus.CREATED)]

    @api.patch("/staff/<staff_dbid>/training/<entry_id>/")
    def update_training(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        body = self.request.json() or {}
        entry = train_update(entry_id, body)
        if entry is None:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(train_serialize(entry))]

    @api.delete("/staff/<staff_dbid>/training/<entry_id>/")
    def delete_training(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        ok = train_delete(entry_id)
        if not ok:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"deleted": True})]

    # ----- Specialty -----

    @api.post("/staff/<staff_dbid>/specialty/")
    def add_specialty(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        staff_dbid = _parse_int(self.request.path_params.get("staff_dbid"))
        body = self.request.json() or {}
        try:
            entry = spec_create(
                staff_dbid,
                nucc_code=body.get("nucc_code", ""),
                is_primary=bool(body.get("is_primary", False)),
            )
        except SpecialtyError as exc:
            return [JSONResponse({"error": str(exc)}, status_code=HTTPStatus.BAD_REQUEST)]
        return [JSONResponse(spec_serialize(entry), status_code=HTTPStatus.CREATED)]

    @api.post("/staff/<staff_dbid>/specialty/<entry_id>/primary/")
    def set_primary_specialty(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        entry = spec_set_primary(entry_id)
        if entry is None:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(spec_serialize(entry))]

    @api.delete("/staff/<staff_dbid>/specialty/<entry_id>/")
    def delete_specialty(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        ok = spec_delete(entry_id)
        if not ok:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"deleted": True})]

    # ----- Certification -----

    @api.post("/staff/<staff_dbid>/certification/")
    def add_certification(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        staff_dbid = _parse_int(self.request.path_params.get("staff_dbid"))
        body = self.request.json() or {}
        entry = cert_create(staff_dbid, body)
        return [JSONResponse(cert_serialize(entry), status_code=HTTPStatus.CREATED)]

    @api.patch("/staff/<staff_dbid>/certification/<entry_id>/")
    def update_certification(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        body = self.request.json() or {}
        entry = cert_update(entry_id, body)
        if entry is None:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse(cert_serialize(entry))]

    @api.delete("/staff/<staff_dbid>/certification/<entry_id>/")
    def delete_certification(self) -> list[Response | Effect]:
        denial = self._require_admin()
        if denial:
            return [denial]
        entry_id = _parse_int(self.request.path_params.get("entry_id"))
        ok = cert_delete(entry_id)
        if not ok:
            return [JSONResponse({"error": "Entry not found"}, status_code=HTTPStatus.NOT_FOUND)]
        return [JSONResponse({"deleted": True})]


def _parse_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
