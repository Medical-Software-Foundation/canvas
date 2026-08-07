"""Staff-authenticated endpoints for waitlist entries."""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from scheduling_waitlist.constants import STATUS_REMOVED
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.entries import (
    DuplicateEntryError,
    create_entry,
    get_entry,
    list_entries,
    normalize_limit,
    normalize_offset,
    normalize_sort,
    update_entry,
)
from scheduling_waitlist.services.options import build_options
from scheduling_waitlist.services.permissions import (
    can_manage_all,
    can_modify_entry,
    staff_from_session,
)
from scheduling_waitlist.services.serializers import serialize_entry
from scheduling_waitlist.services.transitions import TransitionError, apply_transition
from scheduling_waitlist.services.validation import validate_entry

SESSION_HEADER = "canvas-logged-in-user-id"


class WaitlistAPI(StaffSessionAuthMixin, SimpleAPI):
    """Entry CRUD and the choices the roster and forms are built from."""

    PREFIX = "/waitlist"

    # -- request helpers -------------------------------------------------

    def _config(self) -> WaitlistConfig:
        return WaitlistConfig.from_secrets(self.secrets)

    def _acting_staff(self) -> Any | None:
        """The signed-in staff member, taken only from the session header.

        Never from the request body: a caller could name anyone.
        """
        return staff_from_session(self.request.headers.get(SESSION_HEADER, ""))

    @staticmethod
    def _unauthenticated() -> JSONResponse:
        return JSONResponse(
            {"error": "Could not identify the signed-in staff member."},
            status_code=HTTPStatus.UNAUTHORIZED,
        )

    @staticmethod
    def _invalid(field: str, message: str) -> JSONResponse:
        return JSONResponse(
            {"error": "The request could not be understood.", "field_errors": {field: message}},
            status_code=HTTPStatus.BAD_REQUEST,
        )

    def _query(self, name: str, default: str = "") -> str:
        return (self.request.query_params.get(name) or default).strip()

    # -- routes ----------------------------------------------------------

    @api.get("/options")
    def get_options(self) -> list[Response | Effect]:
        """Everything the filter bar and the add form need, in one call."""
        staff = self._acting_staff()
        if staff is None:
            return [self._unauthenticated()]

        config = self._config()
        payload = build_options(config)
        payload["can_manage_all"] = can_manage_all(staff, config.manager_role_codes)
        payload["current_staff_dbid"] = getattr(staff, "dbid", None)

        return [JSONResponse(payload, status_code=HTTPStatus.OK)]

    @api.get("/entries")
    def get_entries(self) -> list[Response | Effect]:
        """A filtered, sorted page of the roster."""
        staff = self._acting_staff()
        if staff is None:
            return [self._unauthenticated()]

        limit = normalize_limit(self.request.query_params.get("limit"))
        if limit is None:
            return [self._invalid("limit", "Must be a whole number.")]

        offset = normalize_offset(self.request.query_params.get("offset"))
        if offset is None:
            return [self._invalid("offset", "Must be a whole number.")]

        sort_key, descending = normalize_sort(self.request.query_params.get("sort"))

        config = self._config()
        manages_all = can_manage_all(staff, config.manager_role_codes)

        entries, total = list_entries(
            limit=limit,
            offset=offset,
            status=self._query("status"),
            search=self._query("q"),
            note_type_dbid=self._query("appointment_type_id") or None,
            provider_dbid=self._query("provider_id") or None,
            location_dbid=self._query("location_id") or None,
            priority_label=self._query("priority"),
            sort=sort_key,
            descending=descending,
        )

        today = datetime.now(timezone.utc).date()
        return [
            JSONResponse(
                {
                    "entries": [
                        serialize_entry(
                            entry,
                            config=config,
                            today=today,
                            viewer=staff,
                            manages_all=manages_all,
                        )
                        for entry in entries
                    ],
                    "count": len(entries),
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "sort": f"-{sort_key}" if descending else sort_key,
                    "can_manage_all": manages_all,
                    "current_staff_dbid": getattr(staff, "dbid", None),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.post("/entries")
    def create(self) -> list[Response | Effect]:
        """Add a patient to the waitlist.

        Used by the roster, the chart-header button, and the button on a
        cancelled appointment; they differ only in what they pre-fill.
        """
        staff = self._acting_staff()
        if staff is None:
            return [self._unauthenticated()]

        config = self._config()
        today = datetime.now(timezone.utc).date()
        result = validate_entry(self.request.json(), config=config, today=today)
        if not result.ok:
            return [
                JSONResponse(
                    {"error": "Some details need fixing.", "field_errors": result.errors},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        try:
            entry = create_entry(
                created_by_dbid=getattr(staff, "dbid", None), **result.cleaned
            )
        except DuplicateEntryError:
            return [
                JSONResponse(
                    {"error": "That patient is already waiting for this service."},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        # Re-read so the response carries the related rows the roster renders.
        stored = get_entry(getattr(entry, "dbid", None)) or entry
        manages_all = can_manage_all(staff, config.manager_role_codes)
        return [
            JSONResponse(
                serialize_entry(
                    stored,
                    config=config,
                    today=today,
                    viewer=staff,
                    manages_all=manages_all,
                ),
                status_code=HTTPStatus.CREATED,
            )
        ]

    # -- write routes ----------------------------------------------------

    def _entry_for_write(self, staff: Any, config: WaitlistConfig):
        """Resolve the addressed entry and check the caller may change it.

        Returns ``(entry, None)`` when allowed, or ``(None, response)``.
        """
        entry = get_entry(self.request.path_params.get("entry_dbid"))
        if entry is None:
            return None, JSONResponse(
                {"error": "That waitlist entry no longer exists."},
                status_code=HTTPStatus.NOT_FOUND,
            )

        manages_all = can_manage_all(staff, config.manager_role_codes)
        if not can_modify_entry(entry, staff, manages_all):
            return None, JSONResponse(
                {"error": "You can only change waitlist entries you added."},
                status_code=HTTPStatus.FORBIDDEN,
            )
        return entry, None

    def _serialized(self, entry, staff, config, today) -> JSONResponse:
        return JSONResponse(
            serialize_entry(
                entry,
                config=config,
                today=today,
                viewer=staff,
                manages_all=can_manage_all(staff, config.manager_role_codes),
            ),
            status_code=HTTPStatus.OK,
        )

    @api.put("/entries/<entry_dbid>")
    def update(self) -> list[Response | Effect]:
        """Edit an entry. The patient is fixed and cannot be reassigned."""
        staff = self._acting_staff()
        if staff is None:
            return [self._unauthenticated()]

        config = self._config()
        entry, refusal = self._entry_for_write(staff, config)
        if refusal is not None:
            return [refusal]

        today = datetime.now(timezone.utc).date()
        result = validate_entry(
            self.request.json(), config=config, today=today, require_patient=False
        )
        if not result.ok:
            return [
                JSONResponse(
                    {"error": "Some details need fixing.", "field_errors": result.errors},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        updated = update_entry(entry, **result.cleaned)
        return [self._serialized(updated, staff, config, today)]

    @api.post("/entries/<entry_dbid>/status")
    def change_status(self) -> list[Response | Effect]:
        """Mark an entry scheduled, offered, removed, or put it back on the list."""
        staff = self._acting_staff()
        if staff is None:
            return [self._unauthenticated()]

        config = self._config()
        entry, refusal = self._entry_for_write(staff, config)
        if refusal is not None:
            return [refusal]

        body = self.request.json() or {}
        to_status = str(body.get("status") or "").strip()
        reason = str(body.get("reason") or "").strip()

        try:
            apply_transition(
                entry,
                to_status=to_status,
                reason=reason,
                actor_dbid=getattr(staff, "dbid", None),
            )
        except TransitionError as exc:
            return [
                JSONResponse(
                    {"error": str(exc), "field_errors": {"status": str(exc)}},
                    status_code=HTTPStatus.CONFLICT,
                )
            ]

        today = datetime.now(timezone.utc).date()
        refreshed = get_entry(getattr(entry, "dbid", None)) or entry
        return [self._serialized(refreshed, staff, config, today)]

    @api.delete("/entries/<entry_dbid>")
    def remove(self) -> list[Response | Effect]:
        """Take an entry off the list.

        A soft removal: the row stays so the wait-time reporting and the record
        of who removed it survive.
        """
        staff = self._acting_staff()
        if staff is None:
            return [self._unauthenticated()]

        config = self._config()
        entry, refusal = self._entry_for_write(staff, config)
        if refusal is not None:
            return [refusal]

        reason = (self.request.query_params.get("reason") or "").strip()
        try:
            apply_transition(
                entry,
                to_status=STATUS_REMOVED,
                reason=reason,
                actor_dbid=getattr(staff, "dbid", None),
            )
        except TransitionError as exc:
            return [
                JSONResponse({"error": str(exc)}, status_code=HTTPStatus.CONFLICT)
            ]

        return [
            JSONResponse(
                {"dbid": getattr(entry, "dbid", None), "status": STATUS_REMOVED},
                status_code=HTTPStatus.OK,
            )
        ]
