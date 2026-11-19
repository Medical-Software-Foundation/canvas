"""CRUD endpoint for clinical favorites."""

import json
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from logger import log

from clinical_favorites.services import FavoritesService


def _parse_body(request: Any) -> dict[str, Any]:
    try:
        return request.json()
    except Exception:
        raw = request.body
        if hasattr(raw, "decode"):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}


class FavoritesAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Manage clinical favorites across types."""

    PATH = "/routes/favorites"

    def _service(self) -> FavoritesService:
        return FavoritesService()

    def _staff_id(self) -> str:
        return self.request.headers.get("canvas-logged-in-user-id", "")

    def get(self) -> list[Response | Effect]:
        staff_id = self._staff_id()
        if not staff_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Staff ID not found"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        favorites = self._service().get_all_favorites(
            staff_id=staff_id,
            visibility_filter=self.request.query_params.get("filter", "all").strip() or "all",
            favorite_type=self.request.query_params.get("type", "").strip() or None,
            include_hidden=self.request.query_params.get("include_hidden", "").strip() == "true",
        )
        return [
            JSONResponse(
                {"success": True, "favorites": favorites, "count": len(favorites)}
            )
        ]

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

        favorite_type = (payload.get("favorite_type") or "").strip()
        if favorite_type not in ("medication", "condition"):
            return [
                JSONResponse(
                    {"success": False, "error": "favorite_type must be medication or condition"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            created = self._service().save_favorite(
                favorite_type=favorite_type,
                payload=payload,
                staff_id=staff_id,
            )
        except ValueError as exc:
            return [
                JSONResponse(
                    {"success": False, "error": str(exc)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(f"Created clinical favorite for staff {staff_id} ({favorite_type})")
        return [JSONResponse({"success": True, "favorite": created})]

    def put(self) -> list[Response | Effect]:
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

        favorite_id = (payload.get("id") or "").strip()
        if not favorite_id:
            return [
                JSONResponse(
                    {"success": False, "error": "id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        service = self._service()
        existing = service.get_favorite_by_id(favorite_id)
        if not existing:
            return [
                JSONResponse(
                    {"success": False, "error": "Favorite not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        if existing.get("created_by_id") != staff_id:
            creator_name = existing.get("created_by_name") or "another staff member"
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": f"Created by {creator_name}, only the creator can edit",
                    },
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        try:
            updated = service.update_favorite(favorite_id, payload)
        except ValueError as exc:
            return [
                JSONResponse(
                    {"success": False, "error": str(exc)},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]
        if not updated:
            return [
                JSONResponse(
                    {"success": False, "error": "Favorite not found after update"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        return [JSONResponse({"success": True, "favorite": updated})]

    def delete(self) -> list[Response | Effect]:
        staff_id = self._staff_id()
        if not staff_id:
            return [
                JSONResponse(
                    {"success": False, "error": "Staff ID not found"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        favorite_id = (self.request.query_params.get("id") or "").strip()
        if not favorite_id:
            return [
                JSONResponse(
                    {"success": False, "error": "id is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        service = self._service()
        existing = service.get_favorite_by_id(favorite_id)
        if not existing:
            return [
                JSONResponse(
                    {"success": False, "error": "Favorite not found"},
                    status_code=HTTPStatus.NOT_FOUND,
                )
            ]
        if existing.get("created_by_id") != staff_id:
            creator_name = existing.get("created_by_name") or "another staff member"
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": f"Created by {creator_name}, only the creator can delete",
                    },
                    status_code=HTTPStatus.FORBIDDEN,
                )
            ]

        deleted = service.delete_favorite(favorite_id)
        if not deleted:
            return [
                JSONResponse(
                    {"success": False, "error": "Delete failed"},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
        return [JSONResponse({"success": True})]
