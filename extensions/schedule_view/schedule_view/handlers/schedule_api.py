"""Schedule view API handler.

Serves the HTML shell and a JSON data endpoint for the BLH enriched schedule calendar.
"""

from datetime import datetime, date, timezone, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from canvas_sdk.effects import Effect
from canvas_sdk.effects.appointments_metadata import AppointmentsMetadata
from canvas_sdk.effects.note.appointment import (
    AddAppointmentLabel,
    Appointment as AppointmentEffect,
    RemoveAppointmentLabel,
)
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.v1.data.calendar import Calendar, Event as CalendarEvent
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note, NoteStates
from canvas_sdk.handlers.simple_api import SessionCredentials, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff
from canvas_sdk.v1.data.task import TaskLabel

from logger import log


# ── Calendar block helpers (adapted from scheduling_with_rooms) ──────────

_DAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _parse_rrule(rrule_str):
    """Parse an RRULE string into a dict of key=value components."""
    rule = rrule_str.replace("RRULE:", "")
    result = {}
    for part in rule.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def _event_occurs_on_date(event, target_date):
    """Check if a (possibly recurring) calendar event occurs on target_date."""
    if not event.starts_at:
        return False
    if not event.recurrence:
        return bool(event.starts_at.date() == target_date)
    if target_date < event.starts_at.date():
        return False
    if event.recurrence_ends_at and target_date > event.recurrence_ends_at.date():
        return False

    rule = _parse_rrule(event.recurrence)
    freq = rule.get("FREQ", "")

    until_str = rule.get("UNTIL")
    if until_str:
        try:
            until_dt = datetime.strptime(until_str[:15], "%Y%m%dT%H%M%S")
            if target_date > until_dt.date():
                return False
        except ValueError:
            pass

    interval = int(rule.get("INTERVAL", "1"))

    if freq == "DAILY":
        if interval == 1:
            return True
        days_diff = (target_date - event.starts_at.date()).days
        return bool(days_diff % interval == 0)

    if freq == "WEEKLY":
        byday = rule.get("BYDAY", "")
        allowed_days = {
            _DAY_MAP[d.strip()]
            for d in byday.split(",")
            if d.strip() in _DAY_MAP
        }
        if not allowed_days:
            allowed_days = {event.starts_at.weekday()}
        if target_date.weekday() not in allowed_days:
            return False
        if interval > 1:
            weeks_diff = (target_date - event.starts_at.date()).days // 7
            if weeks_diff % interval != 0:
                return False
        return True

    return False


def _event_window_on_date(event, target_date, calendar_tz):
    """Return the (naive-local) start/end window for an event on target_date."""
    if not event.starts_at or not event.ends_at:
        return None
    local_start = event.starts_at.astimezone(calendar_tz)
    local_end = event.ends_at.astimezone(calendar_tz)

    window_start = datetime(
        target_date.year, target_date.month, target_date.day,
        local_start.hour, local_start.minute, local_start.second,
    )
    if local_end.date() > local_start.date():
        window_end = datetime(
            target_date.year, target_date.month, target_date.day, 23, 59, 59,
        )
    else:
        window_end = datetime(
            target_date.year, target_date.month, target_date.day,
            local_end.hour, local_end.minute, local_end.second,
        )
    if window_end <= window_start:
        return None
    return (window_start, window_end)


def _parse_calendar_title(title):
    """Parse calendar title into (staff_name, type, location|None)."""
    parts = [p.strip() for p in title.split(":")]
    if len(parts) >= 3:
        return parts[0], parts[1], ":".join(parts[2:]).strip()
    if len(parts) == 2:
        return parts[0], parts[1], None
    return title.strip(), "", None


def _get_calendar_blocks(target_date, staff_dbid_map):
    """Query all Clinic (availability) and Administrative (busy) calendar events for target_date.

    Returns a list of dicts ready for the frontend, each with:
      block_type: "available" or "busy"
      title, provider_name, provider_id, location_name, start_time, end_time, duration_minutes
    """
    from django.db.models import Q

    # Fetch all relevant calendars in one query
    calendars = list(
        Calendar.objects.filter(
            Q(title__icontains=": Clinic") | Q(title__icontains=": admin")
        )
    )
    if not calendars:
        return []

    # Fetch all non-cancelled events for these calendars
    events_by_cal = {}
    for ev in CalendarEvent.objects.filter(calendar__in=calendars, is_cancelled=False):
        events_by_cal.setdefault(ev.calendar_id, []).append(ev)

    blocks = []
    for cal in calendars:
        staff_name, cal_type, cal_location = _parse_calendar_title(cal.title)
        cal_type_lower = cal_type.strip().lower()

        if "clinic" in cal_type_lower:
            block_type = "available"
        elif "admin" in cal_type_lower:
            block_type = "busy"
        else:
            continue

        # Resolve provider_id (dbid) from staff name
        provider_id = staff_dbid_map.get(staff_name, "")

        tz_name = str(cal.timezone) if cal.timezone else "UTC"
        try:
            calendar_tz = ZoneInfo(tz_name)
        except (KeyError, ValueError):
            calendar_tz = ZoneInfo("UTC")

        for event in events_by_cal.get(cal.pk, []):
            if _event_occurs_on_date(event, target_date):
                window = _event_window_on_date(event, target_date, calendar_tz)
                if window:
                    start_dt, end_dt = window
                    duration = int((end_dt - start_dt).total_seconds() / 60)
                    blocks.append({
                        "id": f"cal-{event.pk}",
                        "block_type": block_type,
                        "title": event.title or ("Available" if block_type == "available" else "Block"),
                        "provider_name": staff_name,
                        "provider_id": provider_id,
                        "location_name": cal_location or "",
                        "start_time": start_dt.isoformat(),
                        "end_time": end_dt.isoformat(),
                        "duration_minutes": duration,
                        "is_calendar_block": True,
                    })

    blocks.sort(key=lambda b: b["start_time"])
    return blocks

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))

# Brand theming: map secret names to CSS variable names
_BRAND_OVERRIDES = {
    "BRAND_PRIMARY": "--color-primary",
    "BRAND_PRIMARY_HOVER": "--color-primary-hover",
    "BRAND_PRIMARY_TINT_BG": "--color-primary-bg",
    "BRAND_PRIMARY_TINT_TEXT": "--color-primary-text",
}

import re as _re
_HEX_RE = _re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FONT_RE = _re.compile(r"^[A-Za-z0-9 ,\-'\"\.]+$")
_FONT_URL_RE = _re.compile(r"^https://fonts\.googleapis\.com/css2?\?[A-Za-z0-9=:&;,@_+\-\.%]+$")


def _parse_hour(value, default):
    """Parse a GRID_START_HOUR or GRID_END_HOUR secret to an int 0–23, or return the default."""
    if not value:
        return default
    try:
        h = int(str(value).strip())
        if 0 <= h <= 23:
            return h
    except (ValueError, TypeError):
        pass
    return default


def _build_theme_style(secrets):
    """Build a <style> block with CSS variable overrides from BRAND_* secrets."""
    overrides = []
    for secret_key, css_var in _BRAND_OVERRIDES.items():
        val = (secrets.get(secret_key) or "").strip()
        if val and _HEX_RE.match(val):
            overrides.append(f"  {css_var}: {val};")

    font_stack = (secrets.get("BRAND_FONT_STACK") or "").strip()
    if font_stack and _FONT_RE.match(font_stack):
        overrides.append(f"  --font: {font_stack};")

    parts = []
    font_url = (secrets.get("BRAND_FONT_URL") or "").strip()
    if font_url and _FONT_URL_RE.match(font_url):
        parts.append(f'<link href="{font_url}" rel="stylesheet">')

    if overrides:
        parts.append("<style>:root {\n" + "\n".join(overrides) + "\n}</style>")

    return "\n".join(parts)

# Status display metadata — label and CSS class
STATUS_META = {
    AppointmentProgressStatus.UNCONFIRMED: {"label": "Unconfirmed", "css": "status-unconfirmed"},
    AppointmentProgressStatus.ATTEMPTED: {"label": "Attempted", "css": "status-attempted"},
    AppointmentProgressStatus.CONFIRMED: {"label": "Confirmed", "css": "status-confirmed"},
    AppointmentProgressStatus.ARRIVED: {"label": "Arrived", "css": "status-arrived"},
    AppointmentProgressStatus.ROOMED: {"label": "Roomed", "css": "status-roomed"},
    AppointmentProgressStatus.EXITED: {"label": "Exited", "css": "status-exited"},
    AppointmentProgressStatus.NOSHOWED: {"label": "No Show", "css": "status-noshowed"},
    AppointmentProgressStatus.CANCELLED: {"label": "Cancelled", "css": "status-cancelled"},
}


def _serialize_appointment(appt):
    """Serialize a single appointment to a dict for the frontend."""
    start = appt.start_time
    end = start + timedelta(minutes=appt.duration_minutes) if start and appt.duration_minutes else None

    provider_name = ""
    if appt.provider_id:
        provider_name = f"{appt.provider.first_name} {appt.provider.last_name}".strip()

    patient_name = ""
    patient_key = ""
    if appt.patient_id:
        patient_name = f"{appt.patient.first_name} {appt.patient.last_name}".strip()
        patient_key = appt.patient.id or ""

    location_name = appt.location.full_name if appt.location_id else ""

    note_type_name = appt.note_type.name if appt.note_type_id else ""
    note_type_id = str(appt.note_type.id) if appt.note_type_id else ""
    note_type_code = appt.note_type.code if appt.note_type_id and hasattr(appt.note_type, "code") else ""

    labels = []
    for apt_label in appt.labels.all():
        labels.append({
            "name": apt_label.name,
            "color": apt_label.color or "grey",
        })

    status = appt.status or ""
    status_info = STATUS_META.get(status, {"label": status.title(), "css": "status-unknown"})

    # Prefer metadata note over native comment field
    meta_note = ""
    for m in appt.metadata.all():
        if m.key == "schedule_view:note":
            meta_note = m.value or ""
            break
    comment = meta_note or appt.comment or ""

    return {
        "id": str(appt.id),
        "dbid": str(appt.dbid) if hasattr(appt, "dbid") else "",
        "start_time": start.isoformat() if start else None,
        "end_time": end.isoformat() if end else None,
        "start_display": start.strftime("%-I:%M %p") if start else "",
        "duration_minutes": appt.duration_minutes,
        "patient_name": patient_name,
        "patient_id": str(appt.patient_id) if appt.patient_id else "",
        "patient_uuid": str(appt.patient.id) if appt.patient_id else "",
        "patient_key": str(patient_key),
        "provider_name": provider_name,
        "provider_id": str(appt.provider_id) if appt.provider_id else "",
        "provider_uuid": str(appt.provider.id) if appt.provider_id else "",
        "location_name": location_name,
        "location_id": str(appt.location_id) if appt.location_id else "",
        "location_uuid": str(appt.location.id) if appt.location_id else "",
        "note_type_name": note_type_name,
        "note_type_id": note_type_id,
        "note_type_code": note_type_code,
        "status": status,
        "status_label": status_info["label"],
        "status_css": status_info["css"],
        "labels": labels,
        "comment": comment,
        "note_id": str(appt.note_id) if appt.note_id else "",
        "is_schedule_event": not bool(appt.note_id),
        "is_block": not bool(appt.patient_id) and not bool(appt.note_id) and not bool(appt.parent_appointment_id),
        "parent_appointment_id": str(appt.parent_appointment_id) if appt.parent_appointment_id else "",
    }


class ScheduleViewAPI(SimpleAPI):
    """Serves the BLH enriched schedule view pages and data."""

    PREFIX = "/schedule"

    def authenticate(self, credentials: SessionCredentials) -> bool:
        """Allow any logged-in staff member."""
        return credentials.logged_in_user is not None

    @api.get("/view")
    def schedule_view(self) -> list[Response | Effect]:
        """Serve the HTML shell for the schedule calendar."""
        logged_in_user_id = self.request.headers.get("canvas-logged-in-user-id", "")
        staff_name = ""
        if logged_in_user_id:
            try:
                staff = Staff.objects.get(id=logged_in_user_id)
                staff_name = staff.full_name
            except Staff.DoesNotExist:
                pass

        grid_start = _parse_hour(self.secrets.get("GRID_START_HOUR"), default=7)
        grid_end = _parse_hour(self.secrets.get("GRID_END_HOUR"), default=18)

        context = {
            "staff_name": staff_name,
            "cache_bust": _CACHE_BUST,
            "theme_style": _build_theme_style(self.secrets),
            "grid_start_hour": grid_start,
            "grid_end_hour": grid_end,
        }
        return [
            HTMLResponse(
                render_to_string("templates/schedule_view.html", context),
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/appointments")
    def appointments(self) -> list[Response | Effect]:
        """Return appointment data as JSON for the requested date.

        Query params:
          - date: ISO date string YYYY-MM-DD (defaults to today)
          - provider_id: optional staff key filter
          - location_id: optional location id filter
        """
        date_param = self.request.query_params.get("date", "")
        provider_id = self.request.query_params.get("provider_id", "")
        location_id = self.request.query_params.get("location_id", "")

        try:
            if date_param:
                target_date = date.fromisoformat(date_param)
            else:
                target_date = datetime.now(timezone.utc).date()
        except ValueError:
            return [JSONResponse({"error": "Invalid date format"}, status_code=HTTPStatus.BAD_REQUEST)]

        qs = (
            Appointment.objects
            .filter(
                start_time__date=target_date,
                entered_in_error__isnull=True,
            )
            .exclude(status=AppointmentProgressStatus.CANCELLED)
            .exclude(note__current_state__state=NoteStates.DELETED)
            .select_related("patient", "provider", "location", "note_type")
            .prefetch_related("labels", "metadata")
            .order_by("start_time")
        )

        if provider_id:
            qs = qs.filter(provider__id=provider_id)

        if location_id:
            qs = qs.filter(location__id=location_id)

        # Build set of room-resource provider IDs so we can distinguish
        # room schedule events from regular appointments that lack a note.
        room_provider_ids = set(
            str(s.dbid) for s in Staff.objects.filter(
                active=True, roles__internal_code="RR"
            )
        )

        appointments_data = []
        for appt in qs:
            data = _serialize_appointment(appt)
            # Refine is_schedule_event: only true for room bookings
            # (has parent_appointment_id OR provider is a room resource),
            # not just any appointment missing a note.
            data["is_schedule_event"] = bool(
                data["parent_appointment_id"]
                or data["provider_id"] in room_provider_ids
            ) and not bool(appt.note_id)
            appointments_data.append(data)

        # Cross-reference parent/child appointments to surface room ↔ provider info.
        # Schedule events (room bookings) have parent_appointment_id pointing to the
        # patient appointment. We add room_name to patient appointments and
        # parent_provider_name / parent_note_type_name to schedule events.
        # Build lookup keyed by BOTH UUID (appt.id) and integer dbid
        # (appt.parent_appointment_id is an integer FK, not a UUID).
        by_id = {}
        for a in appointments_data:
            by_id[a["id"]] = a
            if a.get("dbid"):
                by_id[a["dbid"]] = a
        for item in appointments_data:
            if item["is_schedule_event"] and item["parent_appointment_id"]:
                parent = by_id.get(item["parent_appointment_id"])
                if parent:
                    item["parent_provider_name"] = parent["provider_name"]
                    item["parent_note_type_name"] = parent["note_type_name"]
                    item["parent_patient_name"] = parent["patient_name"]
                    item["parent_patient_key"] = parent["patient_key"]
                    # Also give the parent appointment the room name
                    if not parent.get("room_name") and item["provider_name"]:
                        parent["room_name"] = item["provider_name"]
                        parent["rr_staff_id"] = item.get("provider_uuid", item["provider_id"])

        # Fallback: for appointments without a room from cross-referencing
        # (e.g. after reschedule nulls parent_appointment_id), look up the
        # room from note metadata written by scheduling_with_rooms.
        from canvas_sdk.v1.data.note import NoteMetadata
        for item in appointments_data:
            if item.get("room_name") or item.get("is_schedule_event") or item.get("is_block"):
                continue
            if not item.get("note_id"):
                continue
            try:
                # note_id in our serializer is the integer dbid
                room_meta = (
                    NoteMetadata.objects
                    .filter(note__dbid=int(item["note_id"]), key="scheduling_with_rooms:room_staff_key")
                    .values_list("value", flat=True)
                    .first()
                )
                if room_meta:
                    item["rr_staff_id"] = room_meta
                    room_staff = Staff.objects.filter(id=room_meta).first()
                    if room_staff:
                        item["room_name"] = f"{room_staff.first_name} {room_staff.last_name}".strip()
            except (ValueError, Exception):
                pass

        # Build provider list for filter dropdown (from today's appointments)
        provider_ids_seen = set()
        providers = []
        for item in appointments_data:
            pid = item["provider_id"]
            if pid and pid not in provider_ids_seen:
                provider_ids_seen.add(pid)
                providers.append({"id": pid, "name": item["provider_name"]})
        providers.sort(key=lambda p: p["name"])

        # All active clinical providers (for provider column view)
        # Uses SCHEDULABLE_STAFF_ROLES secret if set (same secret as scheduling_with_rooms),
        # otherwise falls back to a broad set of clinical roles. Excludes room resources (RR).
        roles_secret = self.secrets.get("SCHEDULABLE_STAFF_ROLES", "").strip()
        if roles_secret:
            provider_roles = {r.strip() for r in roles_secret.split(",") if r.strip()}
        else:
            provider_roles = {"MD", "DO", "NP", "PA", "LCSW", "PMHNP", "LCPC", "LPC", "LMFT", "PsyD", "PhD", "BCC", "CC"}
        clinical_dbids = set(
            Staff.objects.filter(
                active=True, roles__internal_code__in=provider_roles
            ).exclude(
                roles__internal_code="RR"
            ).values_list("dbid", flat=True)
        )
        all_providers = [
            {"id": str(s.dbid), "name": f"{s.first_name} {s.last_name}".strip()}
            for s in Staff.objects.filter(active=True, dbid__in=clinical_dbids).order_by("schedule_column_ordering", "first_name")
        ]

        # All active practice locations (for location column view)
        # Use dbid to match location_id in appointment serialization
        all_locations = [
            {"id": str(loc.dbid), "name": loc.full_name}
            for loc in PracticeLocation.objects.filter(active=True).order_by("full_name")
        ]

        # All room-resource staff (for rooms column view)
        # Use dbid to match provider_id in appointment serialization
        all_rooms = [
            {"id": str(s.dbid), "name": f"{s.first_name} {s.last_name}".strip()}
            for s in Staff.objects.filter(
                active=True, roles__internal_code="RR"
            ).order_by("schedule_column_ordering", "first_name")
        ]

        # Calendar-based availability and busy blocks (from scheduling_with_rooms calendars)
        # Build a staff name → dbid map for resolving provider_id on blocks
        staff_dbid_map = {}
        for s in Staff.objects.filter(active=True):
            staff_dbid_map[f"{s.first_name} {s.last_name}".strip()] = str(s.dbid)
        calendar_blocks = _get_calendar_blocks(target_date, staff_dbid_map)

        return [
            JSONResponse(
                {
                    "date": target_date.isoformat(),
                    "appointments": appointments_data,
                    "calendar_blocks": calendar_blocks,
                    "providers": providers,
                    "all_providers": all_providers,
                    "all_locations": all_locations,
                    "all_rooms": all_rooms,
                    "count": len(appointments_data),
                },
                status_code=HTTPStatus.OK,
            )
        ]

    @api.get("/styles.css")
    def get_css(self) -> list[Response | Effect]:
        """Serve CSS."""
        return [
            Response(
                render_to_string("templates/schedule_view.css").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/css",
            )
        ]

    @api.get("/app.js")
    def get_js(self) -> list[Response | Effect]:
        """Serve JavaScript."""
        return [
            Response(
                render_to_string("templates/schedule_view.js").encode(),
                status_code=HTTPStatus.OK,
                content_type="text/javascript",
            )
        ]

    @api.get("/labels")
    def labels(self) -> list[Response | Effect]:
        """Return available appointment labels for the label selector."""
        qs = TaskLabel.objects.filter(active=True).order_by("position")
        # Include labels with 'appointments' module OR empty modules (applies to all)
        result = []
        for lbl in qs:
            modules = lbl.modules or []
            if not modules or "appointments" in modules:
                result.append({
                    "id": str(lbl.id),
                    "name": lbl.name,
                    "color": lbl.color or "grey",
                })
        return [JSONResponse({"labels": result}, status_code=HTTPStatus.OK)]

    VALID_STATUSES = {
        "unconfirmed", "attempted", "confirmed", "arrived", "roomed", "exited",
    }

    @api.post("/appointment/<appointment_id>/status")
    def update_status(self) -> list[Response | Effect]:
        """Update appointment status via SDK Appointment effect."""
        appointment_id = self.request.path_params.get("appointment_id", "")
        try:
            body = self.request.json()
        except Exception:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        new_status = body.get("status", "")
        if new_status not in self.VALID_STATUSES:
            return [JSONResponse(
                {"error": f"Invalid status: {new_status}"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        effect = AppointmentEffect(
            instance_id=appointment_id,
            status=AppointmentProgressStatus(new_status),
        )
        return [effect.update(), JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    @api.post("/appointment/<appointment_id>/comment")
    def update_comment(self) -> list[Response | Effect]:
        """Save a free text note on an appointment via AppointmentsMetadata.

        The SDK Appointment model is a read-only view, so we store the note
        as metadata with key 'schedule_view:note'.
        """
        appointment_id = self.request.path_params.get("appointment_id", "")
        try:
            body = self.request.json()
        except Exception:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        comment = body.get("comment", "")

        meta = AppointmentsMetadata(
            appointment_id=appointment_id,
            key="schedule_view:note",
        )
        return [
            meta.upsert(value=comment),
            JSONResponse({"ok": True, "comment": comment}, status_code=HTTPStatus.OK),
        ]

    @api.post("/appointment/<appointment_id>/add-labels")
    def add_labels(self) -> list[Response | Effect]:
        """Add labels to an appointment via SDK effect."""
        appointment_id = self.request.path_params.get("appointment_id", "")
        try:
            body = self.request.json()
        except Exception:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        label_names = body.get("labels", [])
        if not label_names:
            return [JSONResponse({"error": "No labels provided"}, status_code=HTTPStatus.BAD_REQUEST)]

        effect = AddAppointmentLabel(
            appointment_id=appointment_id,
            labels=set(label_names),
        )
        return [effect.apply(), JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    @api.post("/appointment/<appointment_id>/remove-labels")
    def remove_labels(self) -> list[Response | Effect]:
        """Remove labels from an appointment via SDK effect."""
        appointment_id = self.request.path_params.get("appointment_id", "")
        try:
            body = self.request.json()
        except Exception:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=HTTPStatus.BAD_REQUEST)]

        label_names = body.get("labels", [])
        if not label_names:
            return [JSONResponse({"error": "No labels provided"}, status_code=HTTPStatus.BAD_REQUEST)]

        effect = RemoveAppointmentLabel(
            appointment_id=appointment_id,
            labels=set(label_names),
        )
        return [effect.apply(), JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    CANCELLABLE_NOTE_STATES = {
        NoteStates.BOOKED,
        NoteStates.CONVERTED,
    }

    @api.post("/appointment/<appointment_id>/cancel")
    def cancel_appointment(self) -> list[Response | Effect]:
        """Cancel an appointment via SDK effect.

        Validates the appointment's note state before issuing the cancel effect,
        since effects execute asynchronously and failures are not surfaced to the caller.

        Body (optional JSON):
          suppress_notification (bool): When true, the frontend has already added
          a "Silent Cancel" label so notification plugins can skip the cancellation
          message. Logged here for observability.
        """
        appointment_id = self.request.path_params.get("appointment_id", "")

        suppress_notification = False
        try:
            body = self.request.json()
            suppress_notification = bool(body.get("suppress_notification", False))
        except Exception:
            pass

        try:
            appt = Appointment.objects.select_related("note").get(id=appointment_id)
        except Appointment.DoesNotExist:
            return [JSONResponse(
                {"error": "Appointment not found"},
                status_code=HTTPStatus.NOT_FOUND,
            )]

        if not appt.note_id:
            return [JSONResponse(
                {"error": "Appointment has no associated note and cannot be cancelled"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            current_state = appt.note.current_state.state
        except CurrentNoteStateEvent.DoesNotExist:
            current_state = None

        if current_state and current_state not in self.CANCELLABLE_NOTE_STATES:
            state_label = NoteStates(current_state).label if current_state in NoteStates.values else current_state
            return [JSONResponse(
                {"error": f"Appointment cannot be cancelled — note is in '{state_label}' state"},
                status_code=HTTPStatus.CONFLICT,
            )]

        if suppress_notification:
            log.info(
                "cancel_appointment: suppress_notification=True for appointment %s",
                appointment_id,
            )

        effect = AppointmentEffect(instance_id=appointment_id)
        return [effect.cancel(), JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]

    NOSHOW_ALLOWED_STATES = {NoteStates.BOOKED, NoteStates.REVERTED}

    @api.post("/appointment/<appointment_id>/noshow")
    def noshow_appointment(self) -> list[Response | Effect]:
        """Mark an appointment as no-show via SDK Note.no_show() effect."""
        appointment_id = self.request.path_params.get("appointment_id", "")
        try:
            appt = Appointment.objects.select_related("note").get(id=appointment_id)
        except Appointment.DoesNotExist:
            return [JSONResponse(
                {"error": "Appointment not found"},
                status_code=HTTPStatus.NOT_FOUND,
            )]

        if not appt.note_id:
            return [JSONResponse(
                {"error": "Appointment has no associated note"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]

        try:
            current_state = appt.note.current_state.state
        except CurrentNoteStateEvent.DoesNotExist:
            current_state = None

        if not current_state or current_state not in self.NOSHOW_ALLOWED_STATES:
            if current_state == NoteStates.CONVERTED:
                msg = "Cannot mark as no-show — appointment has already been checked in"
            elif current_state == NoteStates.CANCELLED:
                msg = "Cannot mark as no-show — appointment has already been cancelled"
            elif current_state == NoteStates.NOSHOW:
                msg = "Appointment is already marked as no-show"
            else:
                state_label = (
                    NoteStates(current_state).label
                    if current_state and current_state in NoteStates.values
                    else current_state or "unknown"
                )
                msg = f"Cannot mark as no-show — note is in '{state_label}' state"
            return [JSONResponse({"error": msg}, status_code=HTTPStatus.CONFLICT)]

        # note_id on the appointment is the integer DB key; look up the Note UUID
        try:
            note = Note.objects.get(dbid=appt.note_id)
        except Note.DoesNotExist:
            return [JSONResponse(
                {"error": "Note not found"},
                status_code=HTTPStatus.NOT_FOUND,
            )]

        effect = NoteEffect(instance_id=str(note.id))
        return [effect.no_show(), JSONResponse({"ok": True}, status_code=HTTPStatus.OK)]
