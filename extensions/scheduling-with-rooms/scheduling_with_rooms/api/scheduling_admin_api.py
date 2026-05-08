"""SimpleAPI for the scheduling admin matrix.

Endpoints (all prefixed with /plugin-io/api/scheduling_with_rooms/):
  GET  /admin           — Render the matrix HTML page
  GET  /admin/data      — JSON: visit types, rooms, current mappings
  POST /admin/mappings  — Replace-all save of the matrix
"""

from __future__ import annotations

from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.staff import Staff
from logger import log

from scheduling_with_rooms.models import (
    StaffSlotConfig,
    VisitTypeDuration,
    VisitTypeRoomEvent,
    VisitTypeRoomMapping,
    replace_concurrent_limits,
    replace_durations,
    replace_room_event_codes,
)
from scheduling_with_rooms.utils.staff_lookup import (
    get_room_staff,
    get_schedulable_staff,
    parse_schedulable_roles,
)
from scheduling_with_rooms.utils.theming import theme_style_block


class SchedulingAdminAPI(StaffSessionAuthMixin, SimpleAPI):
    """REST API backing the scheduling admin matrix."""

    PREFIX = None

    @api.get("/admin")
    def admin_page(self) -> list[Response | Effect]:
        html = render_to_string(
            "templates/scheduling_admin.html",
            {"theme_style": theme_style_block(self.secrets)},
        )
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/admin/data")
    def admin_data(self) -> list[Response | Effect]:
        """Return visit types (rows), rooms (cols), current mappings, and config."""
        visit_types = [
            {"id": str(row["id"]), "name": row["name"], "code": row["code"] or ""}
            for row in NoteType.objects.filter(
                is_active=True,
                is_scheduleable=True,
                category="encounter",
            ).values("id", "name", "code").order_by("name")
        ]
        # Drop any visit types missing a code — the matrix is keyed on code.
        visit_types = [v for v in visit_types if v["code"]]

        rooms = [
            {"id": str(s.id), "name": s.full_name}
            for s in Staff.objects.filter(active=True, roles__internal_code="RR")
            .distinct()
            .order_by("first_name", "last_name")
        ]

        mappings: dict[str, list[str]] = {}
        for row in VisitTypeRoomMapping.objects.values("note_type_code", "room_staff_key"):
            mappings.setdefault(row["note_type_code"], []).append(row["room_staff_key"])

        # Available NoteTypes that can serve as the "room is booked" event.
        schedule_event_note_types = [
            {"name": row["name"], "code": row["code"] or ""}
            for row in NoteType.objects.filter(
                category="schedule_event",
                is_active=True,
            ).values("name", "code").order_by("name")
        ]
        schedule_event_note_types = [n for n in schedule_event_note_types if n["code"]]

        # Per-visit-type room event codes.
        room_event_codes: dict[str, str] = {
            row["note_type_code"]: row["room_event_note_type_code"]
            for row in VisitTypeRoomEvent.objects.values(
                "note_type_code", "room_event_note_type_code"
            )
        }

        # Per-visit-type allowed durations.
        durations: dict[str, list[int]] = {}
        for row in VisitTypeDuration.objects.values("note_type_code", "duration_minutes"):
            durations.setdefault(row["note_type_code"], []).append(row["duration_minutes"])
        for code in durations:
            durations[code].sort()

        # Schedulable staff (providers + rooms) with their concurrent-slot limits.
        provider_roles = parse_schedulable_roles(self.secrets.get("SCHEDULABLE_STAFF_ROLES", ""))
        provider_list = [{**s, "role": "provider"} for s in get_schedulable_staff(provider_roles)]
        room_list = [{**s, "role": "room"} for s in get_room_staff()]
        seen: set[str] = set()
        schedulable_staff: list[dict] = []
        for entry in provider_list + room_list:
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            schedulable_staff.append(entry)
        concurrent_limits: dict[str, int] = {
            row["staff_key"]: row["concurrent_limit"]
            for row in StaffSlotConfig.objects.values("staff_key", "concurrent_limit")
        }

        return [JSONResponse(
            {
                "visit_types": visit_types,
                "rooms": rooms,
                "mappings": mappings,
                "room_event_codes": room_event_codes,
                "durations": durations,
                "schedule_event_note_types": schedule_event_note_types,
                "schedulable_staff": schedulable_staff,
                "concurrent_limits": concurrent_limits,
            },
            status_code=HTTPStatus.OK,
        )]

    @api.post("/admin/mappings")
    def save_mappings(self) -> list[Response | Effect]:
        """Save the matrix and the per-visit-type room-event NoteType codes.

        Body shape::

            {
              "mappings": {note_type_code: [room_staff_key, ...]},
              "room_event_codes": {note_type_code: "room", ...},
              "durations": {note_type_code: [30, 60, ...], ...},
              "concurrent_limits": {staff_key: 1, ...}
            }

        All four are replace-all per key present in the payload. Keys
        not present are left untouched. Pass an empty list / empty string
        to clear a value.
        """
        body = self.request.json() or {}
        new_mappings = body.get("mappings", {})
        if not isinstance(new_mappings, dict):
            return [JSONResponse(
                {"error": "`mappings` must be an object."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        # Validate mappings shape before any writes.
        for code, room_keys in new_mappings.items():
            if not isinstance(code, str) or not isinstance(room_keys, list):
                return [JSONResponse(
                    {"error": "Each mapping value must be a list of room IDs."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]

        codes_touched = list(new_mappings.keys())
        VisitTypeRoomMapping.objects.filter(note_type_code__in=codes_touched).delete()

        rows_to_create: list[VisitTypeRoomMapping] = []
        for code, room_keys in new_mappings.items():
            for key in set(room_keys):
                if isinstance(key, str) and key:
                    rows_to_create.append(
                        VisitTypeRoomMapping(note_type_code=code, room_staff_key=key)
                    )
        if rows_to_create:
            VisitTypeRoomMapping.objects.bulk_create(rows_to_create)

        # Save per-visit-type room-event NoteType codes.
        new_event_codes = body.get("room_event_codes", {})
        if not isinstance(new_event_codes, dict):
            return [JSONResponse(
                {"error": "`room_event_codes` must be an object."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        cleaned: dict[str, str] = {}
        for code, event_code in new_event_codes.items():
            if not isinstance(code, str) or not isinstance(event_code, str):
                return [JSONResponse(
                    {"error": "Each room_event_codes entry must be a string→string pair."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
            cleaned[code] = event_code.strip()
        replace_room_event_codes(cleaned)

        # Save per-visit-type allowed durations.
        new_durations = body.get("durations", {})
        if not isinstance(new_durations, dict):
            return [JSONResponse(
                {"error": "`durations` must be an object."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        cleaned_durations: dict[str, list[int]] = {}
        for code, minutes_list in new_durations.items():
            if not isinstance(code, str) or not isinstance(minutes_list, list):
                return [JSONResponse(
                    {"error": "Each durations entry must be a string→list[int] pair."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
            valid: list[int] = []
            for m in minutes_list:
                try:
                    mi = int(m)
                except (TypeError, ValueError):
                    continue
                if mi > 0:
                    valid.append(mi)
            cleaned_durations[code] = sorted(set(valid))
        replace_durations(cleaned_durations)

        # Save per-staff concurrent-slot limits.
        new_limits = body.get("concurrent_limits", {})
        if not isinstance(new_limits, dict):
            return [JSONResponse(
                {"error": "`concurrent_limits` must be an object."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        cleaned_limits: dict[str, int] = {}
        for staff_key, limit in new_limits.items():
            if not isinstance(staff_key, str):
                return [JSONResponse(
                    {"error": "Each concurrent_limits key must be a staff ID string."},
                    status_code=HTTPStatus.BAD_REQUEST,
                )]
            try:
                li = int(limit)
            except (TypeError, ValueError):
                continue
            if li > 0:
                cleaned_limits[staff_key] = li
        replace_concurrent_limits(cleaned_limits)

        log.info(
            "scheduling-admin: saved %d mapping rows, event codes for %d visit types, durations for %d visit types, concurrent limits for %d staff",
            len(rows_to_create), len(cleaned), len(cleaned_durations), len(cleaned_limits),
        )
        return [JSONResponse({"status": "saved", "rows": len(rows_to_create)}, status_code=HTTPStatus.OK)]
