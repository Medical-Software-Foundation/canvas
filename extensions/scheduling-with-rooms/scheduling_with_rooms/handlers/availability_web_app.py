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
        providers = (
            Staff.objects
            .filter(active=True, roles__internal_code__in=role_codes)
            .distinct()
        )
        room_ids = set(
            Staff.objects
            .filter(active=True, roles__internal_code="RR")
            .values_list("id", flat=True)
        )
        locations = PracticeLocation.objects.filter(active=True)
        note_types = NoteType.objects.filter(is_active=True, is_scheduleable=True)
        # All note types (including inactive / non-scheduleable) so existing
        # events can render their `allowed_note_types` by name even when the
        # underlying type has since been deactivated.
        all_note_types = NoteType.objects.all()
        events = Event.objects.all().select_related("calendar").prefetch_related(
            "allowed_note_types"
        )

        # for event in events:
        #     log.info("Event --------------------")
        #     log.info(event.id)
        #     log.info(event.title)
        #     log.info(event.calendar.title)
        #     log.info(event.starts_at)
        #     log.info(event.ends_at)
        #     log.info(event.recurrence)
        #     log.info(event.recurrence_ends_at)
        #     log.info(event.allowed_note_types)

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
                }
                for provider in providers
            ]),
            "locations": _safe_json_for_script([
                {"id": str(location.id), "name": location.full_name, "address": ""}
                for location in locations
            ]),
            "noteTypes": _safe_json_for_script([
                {"id": str(note_type.id), "name": note_type.name} for note_type in note_types
            ]),
            "noteTypeNames": _safe_json_for_script({
                str(nt.id): nt.name for nt in all_note_types
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
            "events": _safe_json_for_script([
                _serialize_event(event, list(providers), list(locations))
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
