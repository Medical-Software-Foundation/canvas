"""Bulk import endpoint for clinical favorites.

Accepts a JSON array of favorite payloads and persists each via FavoritesService.
Per row errors are reported back to the client so the operator can correct and retry.
Not gated by a secret. The plugin is open to any clinician per the merge decision in
000 scope.

A single import is capped at a maximum number of rows to bound memory and request
time. The cap defaults to DEFAULT_MAX_IMPORT_ROWS and a Canvas admin can override it
per instance by setting the optional BULK_IMPORT_MAX_ROWS secret to a positive
integer. A missing, blank, or invalid secret falls back to the default.
"""

import json
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPIRoute, StaffSessionAuthMixin
from logger import log

from clinical_favorites.services import FavoritesService

DEFAULT_MAX_IMPORT_ROWS = 500


def _parse_body(request: Any) -> dict[str, Any]:
    try:
        return request.json()
    except Exception:
        raw = request.body
        if hasattr(raw, "decode"):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}


class BulkImportAPI(StaffSessionAuthMixin, SimpleAPIRoute):
    """Bulk import a list of clinical favorites in one round trip."""

    PATH = "/routes/favorites/bulk-import"

    def _service(self) -> FavoritesService:
        return FavoritesService()

    def _staff_id(self) -> str:
        return self.request.headers.get("canvas-logged-in-user-id", "")

    def _max_import_rows(self) -> int:
        """Resolve the per import row cap, secret override falling back to default."""
        raw = self.secrets.get("BULK_IMPORT_MAX_ROWS")
        if raw is None or str(raw).strip() == "":
            return DEFAULT_MAX_IMPORT_ROWS
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return DEFAULT_MAX_IMPORT_ROWS
        return value if value > 0 else DEFAULT_MAX_IMPORT_ROWS

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

        favorites_in = payload.get("favorites")
        if not isinstance(favorites_in, list) or not favorites_in:
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": "Body must be {favorites: [...]} with at least one row",
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        max_rows = self._max_import_rows()
        if len(favorites_in) > max_rows:
            return [
                JSONResponse(
                    {
                        "success": False,
                        "error": f"Too many favorites in one import, max {max_rows}",
                    },
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        dry_run = bool(payload.get("dry_run", False))

        service = self._service()
        imported = 0
        results: list[dict[str, Any]] = []

        for idx, row in enumerate(favorites_in):
            display_name = row.get("display_name") if isinstance(row, dict) else None
            favorite_type = (
                (row.get("favorite_type") or "").strip() if isinstance(row, dict) else ""
            )

            reason = service.validate_favorite_payload(favorite_type, row)
            if reason:
                results.append({
                    "index": idx,
                    "display_name": display_name,
                    "valid": False,
                    "reason": reason,
                })
                continue

            if dry_run:
                results.append({
                    "index": idx,
                    "display_name": display_name,
                    "valid": True,
                    "reason": None,
                })
                continue

            try:
                service.save_favorite(
                    favorite_type=favorite_type,
                    payload=row,
                    staff_id=staff_id,
                )
                imported += 1
                results.append({
                    "index": idx,
                    "display_name": display_name,
                    "valid": True,
                    "reason": None,
                })
            except ValueError as exc:
                results.append({
                    "index": idx,
                    "display_name": display_name,
                    "valid": False,
                    "reason": str(exc),
                })
            except Exception as exc:
                log.exception(f"Bulk import row {idx} failed unexpectedly")
                results.append({
                    "index": idx,
                    "display_name": display_name,
                    "valid": False,
                    "reason": f"Unexpected error, {exc}",
                })

        skipped = [r for r in results if not r["valid"]]
        log.info(
            f"Bulk import for staff {staff_id}, "
            f"dry_run={dry_run}, imported {imported}, skipped {len(skipped)}"
        )
        return [
            JSONResponse(
                {
                    "success": True,
                    "dry_run": dry_run,
                    "imported": imported,
                    "results": results,
                    "skipped": skipped,
                    "count": imported,
                }
            )
        ]
