"""Per user hide and unhide of seeded defaults."""

import json
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin

from clinical_favorites.services import FavoritesService


def _parse_body(request: Any) -> dict[str, Any]:
    try:
        return request.json()
    except Exception:
        raw = request.body
        if hasattr(raw, "decode"):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}


class HideDefaultAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Hide or unhide a seeded default for the current staff."""

    PATH = "/routes/favorites/hide-default"

    def _service(self) -> FavoritesService:
        return FavoritesService()

    def _staff_id(self) -> str:
        return self.request.headers.get("canvas-logged-in-user-id", "")

    def post(self) -> list[Response | Effect]:
        staff_id = self._staff_id()
        if not staff_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Staff ID not found"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            payload = _parse_body(self.request)
        except Exception as exc:
            return [
                JSONResponse(
                    {"success": False, "error": f"Invalid JSON, {exc}"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        default_id = (payload.get("default_id") or "").strip()
        favorite_type = (payload.get("favorite_type") or "medication").strip()
        if not default_id:
            return [
                JSONResponse(
                    {"success": False, "error": "default_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        result = self._service().hide_default(default_id, favorite_type, staff_id)
        if result is not True:
            return [
                JSONResponse(
                    {"success": False, "error": result or "Failed to hide"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        return [JSONResponse({"success": True})]

    def delete(self) -> list[Response | Effect]:
        staff_id = self._staff_id()
        if not staff_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Staff ID not found"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        default_id = (self.request.query_params.get("default_id") or "").strip()
        if not default_id:
            return [
                JSONResponse(
                    {"success": False, "error": "default_id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        ok = self._service().unhide_default(default_id, staff_id)
        if not ok:
            return [
                JSONResponse(
                    {"success": False, "error": "Default was not hidden"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        return [JSONResponse({"success": True})]
