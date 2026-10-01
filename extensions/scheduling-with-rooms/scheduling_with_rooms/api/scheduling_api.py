"""SimpleAPI handler exposing all scheduling REST endpoints.

Endpoints (all prefixed with /plugin-io/api/scheduling_with_rooms/):
  GET  /modal               — Returns the full scheduling modal HTML
  GET  /patients?q=<search> — Search active patients
  GET  /patient-timezone    — Preferred scheduling timezone for one patient
  GET  /locations           — List all active practice locations
  GET  /providers?location_id=<id>  — Schedulable staff for a location
  GET  /note-types          — Active, scheduleable encounter NoteTypes
  GET  /durations           — Available scheduling durations from environment
  GET  /month-summary       — Bookable slot counts per day for a month
  GET  /all-slots           — Provider and room slot columns for one date
  POST /book                — Create or reschedule an Appointment (+ room event)
"""

from __future__ import annotations

import datetime
from http import HTTPStatus
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.commands import ReasonForVisitCommand
from canvas_sdk.effects.note.appointment import Appointment, ScheduleEvent
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import StaffSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import (
    Appointment as AppointmentModel,
)
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import NoteType
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff
from logger import log

from scheduling_with_rooms.models import (
    VisitTypeRoomMapping,
    get_durations_for,
    get_room_event_code_for,
    prefetch_concurrent_limits,
)
from scheduling_with_rooms.utils.rfv_cache import stash as stash_rfv
from scheduling_with_rooms.utils.rr_event_cache import stash as stash_rr_event
from scheduling_with_rooms.utils.calendar_availability import (
    _fetch_clinic_calendars,
    _fetch_schedulable_staff,
    get_location_timezone,
    get_providers_for_location,
)
from scheduling_with_rooms.utils.patient_timezone import get_patient_timezone
from scheduling_with_rooms.utils.room_link import find_room_events, record_room
from scheduling_with_rooms.utils.scheduling_context import (
    ASSET_VERSION,
    RFV_ACTIVE_STATE,
    RFV_SCHEMA_KEY,
    build_prefill,
)
from scheduling_with_rooms.utils.scheduling_logic import (
    DEFAULT_DURATION_MINUTES,
    build_all_provider_slots,
    build_all_room_slots,
    build_month_slot_counts,
    resolve_room_staff,
    prefetch_blocking_appointments,
)
from scheduling_with_rooms.utils.staff_lookup import parse_schedulable_roles
from scheduling_with_rooms.utils.theming import theme_style_block


def _allowed_room_keys_for(note_type_code: str) -> set[str] | None:
    """Look up the set of RR staff IDs allowed for a given visit-type code.

    Returns:
        - ``None`` if the note type has no mapping rows (no room required).
        - A non-empty ``set[str]`` of RR staff IDs when rooms are required.
    """
    if not note_type_code:
        return None
    keys = set(
        VisitTypeRoomMapping.objects.filter(note_type_code=note_type_code)
        .values_list("room_staff_key", flat=True)
    )
    return keys or None




class SchedulingAPI(StaffSessionAuthMixin, SimpleAPI):
    """REST API for the resource calendar scheduling modal."""

    PREFIX = None

    # ------------------------------------------------------------------
    # Helper: parse schedulable staff role codes from secrets
    # ------------------------------------------------------------------

    def _schedulable_roles(self) -> list[str]:
        return parse_schedulable_roles(self.secrets.get("SCHEDULABLE_STAFF_ROLES", ""))

    # ------------------------------------------------------------------
    # Helper: look up location name from ID
    # ------------------------------------------------------------------

    def _location_name(self, location_id: str) -> str:
        """Return the full_name for a PracticeLocation, or empty string."""
        loc = PracticeLocation.objects.filter(id=location_id).values("full_name").first()
        return loc["full_name"] if loc else ""

    def _staff_name(self, staff_id: str) -> str:
        """Return an active staff member's display name, or empty string.

        Mirrors ``Staff.full_name`` off two columns rather than loading the
        whole instance. Callers that need the model object — the ones seeding
        the availability ``staff_cache`` — fetch it themselves.
        """
        row = (
            Staff.objects.filter(id=staff_id, active=True)
            .values("first_name", "last_name")
            .first()
        )
        return f"{row['first_name']} {row['last_name']}".strip() if row else ""

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @api.get("/modal")
    def modal(self) -> list[Response | Effect]:
        """Return the full scheduling modal HTML.

        All query params are optional and describe the launch context handed to
        ``SchedulingWithRoomsApp`` — ``patient_id``, ``provider_id``,
        ``location_id``, ``appointment_id``, ``note_id``, ``start``, ``end``,
        ``duration``, ``mode``, ``origin``. Whatever resolves is passed to the
        template as ``prefill`` so the modal opens with those fields selected.
        """
        context: dict = {
            "theme_style": theme_style_block(self.secrets),
            "prefill": build_prefill(self.request.query_params),
            "cache_bust": ASSET_VERSION,
        }
        html = render_to_string("templates/scheduling_modal.html", context)
        return [HTMLResponse(html, status_code=HTTPStatus.OK)]

    @api.get("/modal.css")
    def modal_css(self) -> list[Response | Effect]:
        """Serve the modal stylesheet.

        Kept out of the HTML so it's a separately cacheable asset. Colors are
        ``var(--token)`` references resolved by the custom properties
        ``theme_style_block`` writes into the page ``<head>``.
        """
        return [
            Response(
                render_to_string("static/scheduling_modal.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/patients")
    def patients(self) -> list[Response | Effect]:
        """Search active patients by name.

        Query param: q (minimum 1 character)
        Returns: [{id, full_name, birth_date, default_location}]
        """
        query = self.request.query_params.get("q", "").strip()
        if len(query) < 1:
            return [JSONResponse({"error": "Query must be at least 1 character."}, status_code=HTTPStatus.BAD_REQUEST)]

        results = Patient.objects.filter(
            first_name__icontains=query,
            active=True,
        ).values("id", "first_name", "last_name", "birth_date", "last_known_timezone")[:20]

        # Also search by last name to catch cases where the scheduler types the last name first.
        last_name_results = Patient.objects.filter(
            last_name__icontains=query,
            active=True,
        ).values("id", "first_name", "last_name", "birth_date", "last_known_timezone")[:20]

        # Merge and deduplicate by id.
        seen_ids: set[str] = set()
        patients_data: list[dict] = []
        for row in list(results) + list(last_name_results):
            pid = str(row["id"])
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            full_name = f"{row['first_name']} {row['last_name']}".strip()
            dob = row["birth_date"].strftime("%m/%d/%Y") if row["birth_date"] else ""
            patients_data.append(
                {
                    "id": pid,
                    "full_name": full_name,
                    "dob": dob,
                    "timezone": row.get("last_known_timezone") or "",
                }
            )

        # Timezones here are the SDK's last_known_timezone only. Search results
        # are throwaway — the authoritative preferredSchedulingTimezone setting
        # is read once, by /patient-timezone, when a patient is actually picked.
        return [JSONResponse(patients_data, status_code=HTTPStatus.OK)]

    @api.get("/patient-timezone")
    def patient_timezone(self) -> list[Response | Effect]:
        """Return the preferred scheduling timezone for a single patient.

        Called once, when a patient is picked in the modal — search results get
        the cheaper ``last_known_timezone`` instead.

        Query param: patient_id (required)
        Returns: {"timezone": "America/New_York"} or {"timezone": ""}
        """
        patient_id = self.request.query_params.get("patient_id", "").strip()
        if not patient_id:
            return [JSONResponse({"error": "patient_id is required."}, status_code=HTTPStatus.BAD_REQUEST)]

        return [
            JSONResponse(
                {"timezone": get_patient_timezone(patient_id)},
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/locations")
    def locations(self) -> list[Response | Effect]:
        """Return all active practice locations."""
        locs = PracticeLocation.objects.filter(active=True).values("id", "full_name")
        data = [{"id": str(row["id"]), "name": row["full_name"]} for row in locs]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/providers")
    def providers(self) -> list[Response | Effect]:
        """Return schedulable staff for the given location.

        Uses Calendar data to determine provider-location association:
          1. Staff with a "Clinic" calendar explicitly naming this location, OR
          2. Staff with a generic "Clinic" calendar whose primary location matches.

        Query param:
          location_id — optional. When omitted, returns the union of
                        providers across all active practice locations
                        (used by the "All locations" mode).
        """
        location_id = self.request.query_params.get("location_id", "").strip()

        schedulable_roles = self._schedulable_roles()
        if not schedulable_roles:
            log.warning("SCHEDULABLE_STAFF_ROLES secret is empty; returning no providers.")
            return [JSONResponse([], status_code=HTTPStatus.OK)]

        if location_id:
            location_name = self._location_name(location_id)
            if not location_name:
                log.warning("providers: location %s not found", location_id)
                return [JSONResponse([], status_code=HTTPStatus.OK)]

            data = get_providers_for_location(location_name, schedulable_roles)
            log.info(
                "providers: location=%s (%s), returning %d: %s",
                location_id,
                location_name,
                len(data),
                [d["name"] for d in data],
            )
            return [JSONResponse(data, status_code=HTTPStatus.OK)]

        # All locations — union providers across every active practice location.
        location_names = list(
            PracticeLocation.objects.filter(active=True)
            .order_by("full_name")
            .values_list("full_name", flat=True)
        )
        # Fetch the heavy data once and reuse for every location iteration —
        # without this, each location ran its own Calendar+Staff query.
        clinic_calendars = _fetch_clinic_calendars()
        schedulable_staff = _fetch_schedulable_staff(schedulable_roles)
        seen: set[str] = set()
        data = []
        for ln in location_names:
            for prov in get_providers_for_location(
                ln,
                schedulable_roles,
                clinic_calendars=clinic_calendars,
                schedulable_staff=schedulable_staff,
            ):
                if prov["id"] in seen:
                    continue
                seen.add(prov["id"])
                data.append(prov)
        data.sort(key=lambda p: p["name"].lower())
        log.info(
            "providers: all locations, returning %d unique: %s",
            len(data), [d["name"] for d in data],
        )
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/note-types")
    def note_types(self) -> list[Response | Effect]:
        """Return active, scheduleable encounter NoteTypes, ordered by name."""
        nt_qs = NoteType.objects.filter(
            is_active=True,
            is_scheduleable=True,
            category="encounter",
        ).order_by("name").values("id", "name", "code")
        data = [
            {"id": str(row["id"]), "name": row["name"], "code": row["code"] or ""}
            for row in nt_qs
        ]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/durations")
    def durations(self) -> list[Response | Effect]:
        """Return available scheduling durations.

        Query param:
          note_type_code — optional; if the visit type has durations
                           configured in the admin matrix, only those are
                           returned (admin matrix wins over secrets).

        Priority:
          1. Per-visit-type config from the admin matrix (when note_type_code
             provided and rows exist).
          2. SCHEDULE_DURATIONS secret (comma-separated or JSON array of minutes).
          3. Hardcoded fallback: [10, 15, 20, 30, 45, 60].
        """
        # 0. Per-visit-type override.
        note_type_code = self.request.query_params.get("note_type_code", "").strip()
        if note_type_code:
            vt_minutes = get_durations_for(note_type_code)
            if vt_minutes:
                log.info(
                    "durations: visit-type %r → %d configured durations: %s",
                    note_type_code, len(vt_minutes), vt_minutes,
                )
                return [JSONResponse(
                    [{"minutes": m} for m in vt_minutes],
                    status_code=HTTPStatus.OK,
                )]

        # 1. Check secret override.
        raw = self.secrets.get("SCHEDULE_DURATIONS", "").strip()
        if raw:
            import json
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    minutes_list = sorted(set(int(m) for m in parsed if int(m) > 0))
                else:
                    raise ValueError("not a list")
            except (json.JSONDecodeError, TypeError, ValueError):
                minutes_list = sorted(set(
                    int(v.strip()) for v in raw.split(",") if v.strip().isdigit() and int(v.strip()) > 0
                ))
            if minutes_list:
                log.info("durations: loaded %d from SCHEDULE_DURATIONS secret: %s", len(minutes_list), minutes_list)
                return [JSONResponse(
                    [{"minutes": m} for m in minutes_list],
                    status_code=HTTPStatus.OK,
                )]

        # 2. Fallback defaults.
        log.info("durations: using hardcoded defaults")
        data = [{"minutes": m} for m in [10, 15, 20, 30, 45, 60]]
        return [JSONResponse(data, status_code=HTTPStatus.OK)]

    @api.get("/month-summary")
    def month_summary(self) -> list[Response | Effect]:
        """Return per-day slot counts for a calendar month.

        Query params:
          location_id    — required
          year_month     — required (YYYY-MM)
          duration       — required (minutes)
          provider_id    — optional; filter to a single provider
          note_type_code — optional; when the visit type maps to rooms in
                          the admin matrix, days only count if a provider
                          AND an allowed room overlap at the same start time
        Returns: {"days": {"2026-03-01": 12, ...}}
        """
        location_id = self.request.query_params.get("location_id", "").strip()
        year_month = self.request.query_params.get("year_month", "").strip()
        duration_str = self.request.query_params.get("duration", "").strip()
        provider_id_filter = self.request.query_params.get("provider_id", "").strip()
        note_type_code = self.request.query_params.get("note_type_code", "").strip()

        missing = [
            name for name, val in [
                ("location_id", location_id),
                ("year_month", year_month),
                ("duration", duration_str),
            ] if not val
        ]
        if missing:
            return [JSONResponse(
                {"error": f"Missing required params: {', '.join(missing)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            year, month = int(year_month[:4]), int(year_month[5:7])
            duration_minutes = int(duration_str)
        except (ValueError, IndexError):
            return [JSONResponse(
                {"error": "Invalid year_month (YYYY-MM) or duration."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        location_name = self._location_name(location_id)
        schedulable_roles = self._schedulable_roles()

        if provider_id_filter:
            provider_list = [
                {"id": provider_id_filter, "name": self._staff_name(provider_id_filter)}
            ]
        else:
            provider_list = get_providers_for_location(location_name, schedulable_roles) if schedulable_roles else []

        if provider_list:
            timezone = get_location_timezone(provider_list[0]["id"], location_name)
        else:
            timezone = "UTC"

        # When the visit type maps to rooms, intersect with room availability
        # so day colors match what the day view will actually render.
        allowed_room_keys = _allowed_room_keys_for(note_type_code)

        counts = build_month_slot_counts(
            provider_list=provider_list,
            year=year,
            month=month,
            duration_minutes=duration_minutes,
            location_name=location_name,
            calendar_tz=timezone,
            allowed_room_keys=allowed_room_keys,
        )

        return [JSONResponse({"days": counts}, status_code=HTTPStatus.OK)]

    def _location_groups(
        self,
        location_ids: list[str],
        date: str,
        duration_minutes: int,
        note_type_code: str,
        provider_id_filter: str,
    ) -> list[dict]:
        """Build provider/room columns for several locations in one pass.

        "All locations" mode used to issue one ``/all-slots`` request per
        location, each repeating the Calendar, Staff, Appointment and
        StaffSlotConfig queries. Here the heavy reads happen once and every
        location shares them:

        * clinic calendars and schedulable staff — one pair of queries, reused
          by ``get_providers_for_location`` for each location;
        * concurrent limits — one query covering every provider and room;
        * blocking appointments — one query per *distinct calendar timezone*
          (normally one), since the cached windows are timezone-converted.
        """
        schedulable_roles = self._schedulable_roles()
        locations = list(
            PracticeLocation.objects.filter(id__in=location_ids, active=True)
            .order_by("full_name")
            .values("id", "full_name")
        )
        if not locations:
            return []

        clinic_calendars = _fetch_clinic_calendars()
        schedulable_staff = (
            _fetch_schedulable_staff(schedulable_roles) if schedulable_roles else []
        )
        staff_cache: dict = {}
        calendar_cache: dict = {}

        allowed_room_keys = _allowed_room_keys_for(note_type_code)
        room_staff = resolve_room_staff(allowed_room_keys) if allowed_room_keys else []
        room_ids = [str(rr.id) for rr in room_staff]

        # Resolve each location's providers and calendar timezone first, so the
        # prefetches below can cover every staff member at once.
        resolved: list[dict] = []
        for loc in locations:
            loc_id, loc_name = str(loc["id"]), loc["full_name"] or ""
            if provider_id_filter:
                staff_obj = staff_cache.get(provider_id_filter) or Staff.objects.filter(
                    id=provider_id_filter, active=True
                ).first()
                if staff_obj is not None:
                    staff_cache.setdefault(provider_id_filter, staff_obj)
                providers = [
                    {
                        "id": provider_id_filter,
                        "name": staff_obj.full_name if staff_obj else "",
                    }
                ]
            elif schedulable_roles:
                providers = get_providers_for_location(
                    loc_name,
                    schedulable_roles,
                    clinic_calendars=clinic_calendars,
                    schedulable_staff=schedulable_staff,
                )
            else:
                providers = []

            timezone = (
                get_location_timezone(
                    providers[0]["id"],
                    loc_name,
                    staff_cache=staff_cache,
                    calendar_cache=calendar_cache,
                )
                if providers
                else "UTC"
            )
            resolved.append(
                {
                    "location_id": loc_id,
                    "location_name": loc_name,
                    "timezone": timezone,
                    "providers": providers,
                }
            )

        all_staff_ids = room_ids + [
            prov["id"] for entry in resolved for prov in entry["providers"]
        ]
        limit_cache = prefetch_concurrent_limits(all_staff_ids)

        # Cached appointment windows are already converted to a calendar's
        # local time, so they can only be shared between locations that agree
        # on that timezone.
        day_start = datetime.datetime.fromisoformat(date)
        day_end = day_start + datetime.timedelta(days=1)
        booked_by_tz: dict[str, dict] = {}
        for timezone in {entry["timezone"] for entry in resolved}:
            booked_by_tz[timezone] = prefetch_blocking_appointments(
                all_staff_ids, day_start, day_end, timezone
            )

        groups: list[dict] = []
        for entry in resolved:
            timezone = entry["timezone"]
            booked_cache = booked_by_tz[timezone]
            providers_data = build_all_provider_slots(
                provider_list=entry["providers"],
                location_id=entry["location_id"],
                date=date,
                duration_minutes=duration_minutes,
                location_name=entry["location_name"],
                calendar_tz=timezone,
                staff_cache=staff_cache,
                calendar_cache=calendar_cache,
                booked_cache=booked_cache,
                limit_cache=limit_cache,
            )
            rooms_data: list[dict] = []
            if allowed_room_keys:
                rooms_data = build_all_room_slots(
                    date=date,
                    duration_minutes=duration_minutes,
                    location_name=entry["location_name"],
                    calendar_tz=timezone,
                    allowed_room_keys=allowed_room_keys,
                    staff_cache=staff_cache,
                    calendar_cache=calendar_cache,
                    booked_cache=booked_cache,
                    limit_cache=limit_cache,
                    room_staff=room_staff,
                )
            groups.append({**entry, "providers": providers_data, "rooms": rooms_data})
        return groups

    @api.get("/all-slots")
    def all_slots(self) -> list[Response | Effect]:
        """Return provider columns and room columns for a single date.

        Query params:
          location_id    — required unless location_ids is given
          location_ids   — optional comma-separated list; returns a ``locations``
                           array of per-location groups in a single response,
                           for "All locations" mode
          date           — required (YYYY-MM-DD)
          duration       — required (minutes as integer string)
          note_type_code — optional; when mapped to rooms in the admin matrix,
                           those rooms are included as columns
          provider_id    — optional; filter to a single provider
        """
        location_ids_param = self.request.query_params.get("location_ids", "").strip()
        location_id = self.request.query_params.get("location_id", "").strip()
        date = self.request.query_params.get("date", "").strip()
        duration_str = self.request.query_params.get("duration", "").strip()
        note_type_code = self.request.query_params.get("note_type_code", "").strip()
        provider_id_filter = self.request.query_params.get("provider_id", "").strip()

        missing = [
            name
            for name, val in [
                ("location_id", location_id or location_ids_param),
                ("date", date),
                ("duration", duration_str),
            ]
            if not val
        ]
        if missing:
            return [JSONResponse(
                {"error": f"Missing required params: {', '.join(missing)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            duration_minutes = int(duration_str)
        except ValueError:
            return [JSONResponse(
                {"error": "duration must be an integer number of minutes."},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        if location_ids_param:
            location_ids = [
                part.strip() for part in location_ids_param.split(",") if part.strip()
            ]
            groups = self._location_groups(
                location_ids, date, duration_minutes, note_type_code, provider_id_filter
            )
            return [JSONResponse({"locations": groups}, status_code=HTTPStatus.OK)]

        location_name = self._location_name(location_id)

        # Build provider list — either a single provider or all at this location.
        schedulable_roles = self._schedulable_roles()
        if provider_id_filter:
            provider_list = [
                {"id": provider_id_filter, "name": self._staff_name(provider_id_filter)}
            ]
        else:
            provider_list = get_providers_for_location(location_name, schedulable_roles) if schedulable_roles else []

        # Determine timezone from the first available provider, or fallback.
        if provider_list:
            timezone = get_location_timezone(provider_list[0]["id"], location_name)
        else:
            timezone = "UTC"

        providers_data = build_all_provider_slots(
            provider_list=provider_list,
            location_id=location_id,
            date=date,
            duration_minutes=duration_minutes,
            location_name=location_name,
            calendar_tz=timezone,
        )

        # Only fetch room slots if the appointment type requires them.
        rooms_data: list[dict] = []
        allowed_room_keys = _allowed_room_keys_for(note_type_code)
        if allowed_room_keys:
            rooms_data = build_all_room_slots(
                date=date,
                duration_minutes=duration_minutes,
                location_name=location_name,
                calendar_tz=timezone,
                allowed_room_keys=allowed_room_keys,
            )

        return [JSONResponse(
            {"providers": providers_data, "rooms": rooms_data, "timezone": timezone},
            status_code=HTTPStatus.OK,
        )]

    def _reason_for_visit_effects(self, appointment_id: str, text: str) -> list[Effect]:
        """Keep the note's Reason-for-Visit command in step with the modal field.

        The create path defers this to APPOINTMENT_CREATED via the RFV cache,
        but that event doesn't fire for a move, so a reschedule has to edit the
        existing command (or originate one if the note has none) inline.

        A blank field is treated as "leave it alone" rather than "clear it" —
        the modal shows the reason for context, and silently dropping a
        clinician's reason because someone tabbed through would be worse than
        requiring them to clear it on the note itself.
        """
        if not text:
            return []

        appointment = (
            AppointmentModel.objects.select_related("note")
            .filter(id=appointment_id)
            .first()
        )
        if appointment is None or not appointment.note:
            log.warning(
                "book: no note on appointment %s; cannot sync reason for visit",
                appointment_id,
            )
            return []

        note_uuid = str(appointment.note.id)
        existing = (
            Command.objects.filter(
                note__id=note_uuid,
                schema_key=RFV_SCHEMA_KEY,
                state=RFV_ACTIVE_STATE,
            )
            .order_by("-created")
            .values("id", "data")
            .first()
        )

        if existing is None:
            log.info("book: originating RFV on note %s for reschedule", note_uuid)
            return [ReasonForVisitCommand(note_uuid=note_uuid, comment=text).originate()]

        if str((existing["data"] or {}).get("comment") or "").strip() == text:
            return []

        log.info("book: editing RFV command %s on note %s", existing["id"], note_uuid)
        return [
            ReasonForVisitCommand(
                command_uuid=str(existing["id"]),
                note_uuid=note_uuid,
                comment=text,
            ).edit()
        ]

    def _reschedule_room_events(
        self,
        appointment_id: str,
        rr_staff_id: str,
        note_type_code: str,
        start_time: datetime.datetime,
        duration_minutes: int,
        location_id: str,
        patient_id: str,
    ) -> list[Effect]:
        """Move an appointment's room ScheduleEvent to the new time.

        Uses ``ScheduleEvent.reschedule()`` on the existing event rather than
        deleting and re-creating it, which keeps the event history and the
        ``parent_appointment_id`` link intact instead of rebuilding them. It
        also sidesteps the create-path note-type validation entirely: a
        reschedule sets no ``note_type_id``, so the SDK never re-resolves it.

        Changing rooms is handled by the same call — ``provider_id`` moves to
        the newly-chosen RR staff member.

        https://docs.canvasmedical.com/sdk/effect-notes/#reschedule-schedule-event
        """
        effects: list[Effect] = []
        appointment = (
            AppointmentModel.objects.select_related("note")
            .prefetch_related("children__note_type")
            .filter(id=appointment_id)
            .first()
        )
        if appointment is None:
            log.warning("book: appointment %s not found for reschedule", appointment_id)
            return effects

        existing = find_room_events(appointment)
        note_id = str(appointment.note.id) if appointment.note else ""

        allowed_room_keys = _allowed_room_keys_for(note_type_code)
        wants_room = bool(rr_staff_id and allowed_room_keys)

        if not wants_room:
            # Switched to a visit type that needs no room — drop what's there.
            # The note's recorded room is deliberately left as-is: clearing it
            # would lose the trail to any event this pass failed to find.
            for child in existing:
                log.info("book: removing room event %s for %s", child.id, appointment_id)
                effects.append(ScheduleEvent(instance_id=str(child.id)).delete())
            return effects

        if existing:
            # Move the first one; anything beyond that is a duplicate.
            primary, duplicates = existing[0], existing[1:]
            log.info(
                "book: rescheduling room event %s to %s on rr_staff=%s",
                primary.id, start_time.isoformat(), rr_staff_id,
            )
            effects.append(
                ScheduleEvent(
                    instance_id=str(primary.id),
                    start_time=start_time,
                    duration_minutes=duration_minutes,
                    practice_location_id=location_id,
                    provider_id=rr_staff_id,
                ).reschedule()
            )
            for child in duplicates:
                log.info("book: removing duplicate room event %s", child.id)
                effects.append(ScheduleEvent(instance_id=str(child.id)).delete())
            # The scheduler may have picked a different room; keep the note's
            # record current so the next reschedule can still find the event.
            effects.extend(record_room(note_id, rr_staff_id))
            return effects

        # No room event yet — the appointment was booked before rooms were
        # required for this visit type, so create one.
        room_event_code = get_room_event_code_for(note_type_code)
        resource_event_nt = (
            NoteType.objects.filter(
                code=room_event_code,
                category="schedule_event",
                is_active=True,
            ).first()
            if room_event_code
            else None
        )
        if resource_event_nt is None:
            log.warning(
                "book: room ScheduleEvent NoteType not found for visit type %r "
                "(configured code=%r); rescheduled appointment %s has no room event.",
                note_type_code, room_event_code, appointment_id,
            )
            return effects

        effects.append(
            ScheduleEvent(
                note_type_id=str(resource_event_nt.id),
                patient_id=patient_id,
                start_time=start_time,
                duration_minutes=duration_minutes,
                practice_location_id=location_id,
                provider_id=rr_staff_id,
                parent_appointment_id=appointment_id,
                # No description. The create path never set one either (see
                # rr_event_origination), and NoteType.id is not unique on real
                # instances — the SDK re-resolves it without an is_active
                # filter, so it can validate `description` against a different
                # row than the one we'd have checked. The reason for visit
                # lives on the patient's note regardless.
            ).create()
        )
        effects.extend(record_room(note_id, rr_staff_id))
        return effects

    @api.post("/book")
    def book(self) -> list[Response | Effect]:
        """Create (or reschedule) an Appointment and its room ScheduleEvent.

        Expected JSON body:
          patient_id       — UUID string
          provider_id      — UUID string
          location_id      — UUID string
          note_type_id     — UUID string (appointment note type)
          note_type_code   — string (used to look up the room mapping)
          start_time       — ISO 8601 datetime string
          duration_minutes — integer
          rr_staff_id      — optional UUID string (present for resource-required)
          reason_for_visit — optional free text; originated as the RFV command
                             on the appointment's note via APPOINTMENT_CREATED
          appointment_id   — optional UUID string; when present the existing
                             appointment is moved instead of a new one created
                             (the reschedule entry points supply it)
        """
        body = self.request.json()

        patient_id = body.get("patient_id", "").strip()
        provider_id = body.get("provider_id", "").strip()
        location_id = body.get("location_id", "").strip()
        note_type_id = body.get("note_type_id", "").strip()
        note_type_code = body.get("note_type_code", "").strip()
        start_time_str = body.get("start_time", "").strip()
        duration_minutes = body.get("duration_minutes", DEFAULT_DURATION_MINUTES)
        rr_staff_id = body.get("rr_staff_id", "").strip()
        reason_for_visit_text = (body.get("reason_for_visit") or "").strip()
        appointment_id = (body.get("appointment_id") or "").strip()

        # Basic validation.
        required_fields = {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "location_id": location_id,
            "note_type_id": note_type_id,
            "start_time": start_time_str,
            "duration_minutes": duration_minutes,
        }
        missing = [k for k, v in required_fields.items() if not v and v != 0]
        if missing:
            return [JSONResponse(
                {"error": f"Missing required fields: {', '.join(missing)}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        # Slot times are naive in the calendar's local timezone.  Canvas
        # expects UTC, so convert before creating the appointment.
        location_name = self._location_name(location_id)
        calendar_tz_str = get_location_timezone(provider_id, location_name)
        # The slot-search flow sends a naive ISO in the calendar's local
        # timezone; the manual-override flow sends an already-zoned ISO
        # (UTC) computed from the user's browser timezone. Detect tz-aware
        # input and use it as-is; otherwise interpret naive as calendar tz.
        parsed_start = datetime.datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        if parsed_start.tzinfo is not None:
            start_time = parsed_start.astimezone(datetime.timezone.utc)
            log.info(
                "book: zoned input=%s, utc=%s",
                start_time_str, start_time.isoformat(),
            )
        else:
            cal_tz = ZoneInfo(calendar_tz_str)
            start_time = parsed_start.replace(tzinfo=cal_tz).astimezone(datetime.timezone.utc)
            log.info(
                "book: naive=%s, calendar_tz=%s, utc=%s",
                parsed_start.isoformat(), calendar_tz_str, start_time.isoformat(),
            )
        # Default reason for visit to the NoteType name. Filter on is_active:
        # note types are version-controlled, so updating one deprecates the old
        # row and many rows share an id. Without it, .first() returns an
        # arbitrary version's name.
        note_type_obj = (
            NoteType.objects.filter(id=note_type_id, is_active=True)
            .values("name")
            .first()
        )
        reason_for_visit = note_type_obj["name"] if note_type_obj else ""

        effects: list[Effect] = []

        # Reschedule: move the existing appointment rather than booking a
        # second one, then move its room event to match. `.reschedule()` rather
        # than `.update()` so Canvas records the move — it cancels the original
        # and links the replacement via `appointment_rescheduled_from`, which a
        # plain update leaves null.
        # https://docs.canvasmedical.com/sdk/effect-notes/#reschedule-appointment
        # The note already exists and APPOINTMENT_CREATED won't fire, so the RFV
        # goes straight onto the note instead of through the cache stash.
        if appointment_id:
            effects.append(
                Appointment(
                    instance_id=appointment_id,
                    start_time=start_time,
                    duration_minutes=int(duration_minutes),
                    practice_location_id=location_id,
                    provider_id=provider_id,
                ).reschedule()
            )
            effects.extend(
                self._reschedule_room_events(
                    appointment_id=appointment_id,
                    rr_staff_id=rr_staff_id,
                    note_type_code=note_type_code,
                    start_time=start_time,
                    duration_minutes=int(duration_minutes),
                    location_id=location_id,
                    patient_id=patient_id,
                )
            )
            effects.extend(
                self._reason_for_visit_effects(appointment_id, reason_for_visit_text)
            )
            log.info(
                "Rescheduling appointment %s: provider=%s, start=%s",
                appointment_id, provider_id, start_time.isoformat(),
            )
            return [
                JSONResponse(
                    {"status": "rescheduled", "effects_count": len(effects)},
                    status_code=HTTPStatus.OK,
                ),
                *effects,
            ]

        # Stash the user-typed RFV text so the APPOINTMENT_CREATED handler
        # can originate the RFV command on the auto-created note. Keyed by
        # (patient, provider, start_time) since the appointment ID is
        # server-assigned and not yet known here.
        if reason_for_visit_text:
            stash_rfv(patient_id, provider_id, start_time, reason_for_visit_text)

        # 1. Create the patient appointment.
        appt_effect = Appointment(
            appointment_note_type_id=note_type_id,
            patient_id=patient_id,
            start_time=start_time,
            duration_minutes=int(duration_minutes),
            practice_location_id=location_id,
            provider_id=provider_id,
        )
        appt_result = appt_effect.create()
        if isinstance(appt_result, list):
            effects.extend(appt_result)
        else:
            effects.append(appt_result)

        # 2. If this is a resource-required appointment and an RR staff member
        #    was selected, stash the booking intent. The APPOINTMENT_CREATED
        #    handler will create the ScheduleEvent with parent_appointment_id
        #    pointing at the just-created patient Appointment, so cancellation
        #    can cascade via the children relationship instead of via FHIR.
        allowed_room_keys = _allowed_room_keys_for(note_type_code)
        if rr_staff_id and allowed_room_keys:
            room_event_code = get_room_event_code_for(note_type_code)
            resource_event_nt = (
                NoteType.objects.filter(
                    code=room_event_code,
                    category="schedule_event",
                    is_active=True,
                ).first()
                if room_event_code
                else None
            )
            if resource_event_nt is None:
                log.warning(
                    "Room ScheduleEvent NoteType not found for visit type %r "
                    "(configured code=%r); skipping ScheduleEvent creation. "
                    "Set the room event type for this visit type in the "
                    "Scheduling Admin app.",
                    note_type_code, room_event_code,
                )
            else:
                stash_rr_event(
                    patient_id,
                    provider_id,
                    start_time,
                    rr_staff_id=rr_staff_id,
                    note_type_id=str(resource_event_nt.id),
                    duration_minutes=int(duration_minutes),
                    location_id=location_id,
                )

        log.info(
            "Booking appointment: patient=%s, provider=%s, start=%s, reason=%s",
            patient_id,
            provider_id,
            start_time_str,
            reason_for_visit,
        )

        return [
            JSONResponse(
                {"status": "booked", "effects_count": len(effects)},
                status_code=HTTPStatus.CREATED,
            ),
            *effects,
        ]
