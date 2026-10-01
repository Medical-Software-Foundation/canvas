import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import CalendarType, EventRecurrence
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import NoteType, PracticeLocation
from canvas_sdk.v1.data.calendar import Event
from canvas_sdk.v1.data.staff import Staff

from scheduling_with_rooms.api.events import _serialize_event
from scheduling_with_rooms.utils.staff_lookup import parse_schedulable_roles
from scheduling_with_rooms.utils.theming import theme_style_block

# Bumped on every plugin install — appended as ?v=<token> to internal asset
# URLs so returning staff don't hit a stale availability.css / availability.js
# from their browser cache.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


def _safe_json_for_script(value: Any) -> str:
    """JSON-encode ``value`` and escape characters that could break out of a
    ``<script>`` block when inlined via Django's ``|safe`` filter.

    Mirrors what Django's ``json_script`` template tag does internally: escapes
    ``<``, ``>``, ``&``, and ``'`` so a hostile string like
    ``</script><script>alert(1)</script>`` cannot terminate the surrounding
    ``<script>`` tag.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("'", "\\u0027")
    )


class AvailabilityWebApp(StaffSessionAuthMixin, SimpleAPI):
    """A web application for managing availability calendars."""

    PREFIX = "/app"

    # Serve templated HTML
    @api.get("/availability-app")
    def index(self) -> list[Response | Effect]:
        """Serve the main HTML page with context data."""
        logged_in_user_id = self.request.headers.get("canvas-logged-in-user-id")

        # Provider pool: active staff with role codes in the
        # SCHEDULABLE_STAFF_ROLES secret OR rooms (RR). Rooms are unioned in
        # explicitly so the manager can manage their availability too — the
        # UI splits them into a separate Rooms dropdown via `is_room`.
        schedulable_roles = parse_schedulable_roles(
            self.secrets.get("SCHEDULABLE_STAFF_ROLES", "")
        )
        role_codes = list({*schedulable_roles, "RR"})
        providers = list(
            Staff.objects
            .filter(active=True, roles__internal_code__in=role_codes)
            .select_related("primary_practice_location")
            # `credentialed_name` below walks Staff.roles (via
            # top_clinical_role), which is one query per provider without this.
            .prefetch_related("roles")
            .distinct()
        )
        # Rooms come out of the roles already prefetched above rather than a
        # second Staff query.
        room_ids = {
            provider.id
            for provider in providers
            if any(role.internal_code == "RR" for role in provider.roles.all())
        }
        locations = list(
            PracticeLocation.objects.filter(active=True).values("id", "full_name")
        )
        locations_by_name = {row["full_name"]: str(row["id"]) for row in locations}
        note_types = list(
            NoteType.objects.filter(is_active=True, is_scheduleable=True).values("id", "name")
        )
        # Names for every note type an existing event might reference, including
        # ones no longer scheduleable. Note types are version-controlled: an
        # update deprecates the old row, so many rows share an id and only one
        # is active. Ordering by is_active puts the active row last, so building
        # the {id: name} dict below lets the current name win — while a fully
        # retired type still resolves to some name rather than none.
        all_note_types = NoteType.objects.order_by("is_active").values("id", "name")
        events = Event.objects.all().select_related("calendar").prefetch_related(
            "allowed_note_types"
        )

        # Serialize structured data and escape characters that could break out
        # of a <script> block — the template inlines these via `|safe` (see
        # static/availability/index.html), so json.dumps alone leaves a stored
        # XSS hole if any source string contains "</script>".
        context = {
            "providers": _safe_json_for_script([
                {
                    "id": str(provider.id),
                    "name": provider.credentialed_name,
                    "full_name": provider.full_name,
                    "is_room": provider.id in room_ids,
                    # For rooms, this drives the location-aware Rooms dropdown:
                    # the UI only offers a room when its staff profile's
                    # primary_practice_location matches the chosen location.
                    # Use the location's UUID `id` (not the integer FK dbid) so
                    # it matches the location ids the dropdown is built from.
                    "primary_practice_location": (
                        str(provider.primary_practice_location.id)
                        if provider.primary_practice_location
                        else None
                    ),
                }
                for provider in providers
            ]),
            "locations": _safe_json_for_script([
                {"id": str(row["id"]), "name": row["full_name"], "address": ""}
                for row in locations
            ]),
            "noteTypes": _safe_json_for_script([
                {"id": str(row["id"]), "name": row["name"]} for row in note_types
            ]),
            "noteTypeNames": _safe_json_for_script({
                str(row["id"]): row["name"] for row in all_note_types
            }),
            "calendarTypes": _safe_json_for_script([
                {"value": CalendarType.Clinic.value, "label": "Available"},
                {"value": CalendarType.Administrative.value, "label": "Busy"},
            ]),
            "recurrence": _safe_json_for_script([
                {"value": EventRecurrence.Daily.value, "label": "Daily"},
                {"value": EventRecurrence.Weekly.value, "label": "Weekly"},
            ]),
            "loggedInUserId": logged_in_user_id,
            # providers/locations_by_name are built once, not re-materialized
            # per event as `list(providers)` used to do.
            "events": _safe_json_for_script([
                _serialize_event(event, providers, locations_by_name)
                for event in events
            ]),
            "cache_bust": _CACHE_BUST,
            "theme_style": theme_style_block(self.secrets),
        }

        return [
            HTMLResponse(
                render_to_string("static/availability/index.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/availability.js")
    def get_main_js(self) -> list[Response | Effect]:
        """Serve the main JavaScript file."""
        return [
            Response(
                render_to_string("static/availability/main.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/availability.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve the main CSS file."""
        return [
            Response(
                render_to_string("static/availability/styles.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]
