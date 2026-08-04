"""The vocabulary shared between the modal's launchers and the ``/modal`` endpoint.

Canvas hands a ``SchedulingApplication`` a context describing where the
scheduling action came from: entity references delivered as ``{"id": ...}``
plus a few scalars (``start``, ``end``/``duration``, ``mode``, ``origin``).
The application forwards those as query params on the modal URL (``modal_url``)
and ``build_prefill`` turns them back into the labelled objects the modal
template needs in order to pre-select its form fields.

See https://docs.canvasmedical.com/sdk/handlers-embedded-applications/#scheduling-applications

Mapping from context key to modal query param:

    patient     -> patient_id
    provider    -> provider_id
    location    -> location_id
    appointment -> appointment_id
    note        -> note_id

Launchers that carry no context at all — the global panel button — call
``modal_url()`` with no arguments and get an empty-context modal.
"""

from __future__ import annotations

import datetime
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.patient import Patient
from canvas_sdk.v1.data.practicelocation import PracticeLocation
from canvas_sdk.v1.data.staff import Staff
from logger import log

from scheduling_with_rooms.utils.calendar_availability import get_location_timezone

# Context keys carrying an entity reference, and the query param each becomes.
ENTITY_PARAMS: dict[str, str] = {
    "patient": "patient_id",
    "provider": "provider_id",
    "location": "location_id",
    "appointment": "appointment_id",
    "note": "note_id",
}

# Context keys carrying a plain scalar, forwarded under the same name.
SCALAR_PARAMS: tuple[str, ...] = ("start", "end", "duration", "mode", "origin")

VALID_MODES = frozenset({"schedule", "reschedule", "followup"})

DEFAULT_MODE = "schedule"

# Canvas supplies `origin` for its own entry points (schedule_page,
# patient_chart, calendar, calendar_reschedule, note_reschedule). This extra
# value is ours, sent by the global panel button so the modal can tell a
# standalone launch from one Canvas routed to it — the panel has no page
# underneath to return to, so it closes itself after a successful booking.
ORIGIN_GLOBAL_PANEL = "global_panel"

# The booking flow never stores the reason for visit on the Appointment — it
# originates a Reason-for-Visit command on the note instead (see
# handlers/rfv_origination.py), so a reschedule has to read it back from there.
RFV_SCHEMA_KEY = "reasonForVisit"

# A Reason-for-Visit command is never committed — it stays staged for the life
# of the note. Entered-in-error and deleted commands keep their rows, so
# "staged" is exactly the set of reasons still live on a note.
RFV_ACTIVE_STATE = "staged"

MODAL_PATH = "/plugin-io/api/scheduling_with_rooms/modal"

# Bumped on every plugin load. Appended as ?v=<token> to the modal URL and to
# internal CSS asset URLs so a reinstall invalidates anything a browser cached.
# Shared so every launcher and template agrees on one value.
ASSET_VERSION = str(int(datetime.datetime.now(datetime.timezone.utc).timestamp()))


def modal_url(**params: Any) -> str:
    """Build a cache-busted ``/modal`` URL, dropping params with no value."""
    query: dict[str, str] = {"v": ASSET_VERSION}
    query.update(
        {key: str(value) for key, value in params.items() if value not in (None, "")}
    )
    return f"{MODAL_PATH}?{urlencode(query)}"


def _get(query_params: dict, key: str) -> str:
    """Return a stripped string value for ``key``, or ``""``."""
    return str(query_params.get(key) or "").strip()


def _parse_iso(value: str) -> datetime.datetime | None:
    """Parse an ISO-8601 string, tolerating a trailing ``Z``."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        log.warning("scheduling context: unparseable datetime %r", value)
        return None


def _positive_int(value: str | int) -> int | None:
    """Parse a positive integer, or return ``None``."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _patient_prefill(patient_id: str) -> dict[str, str] | None:
    """Resolve a patient key into the chip payload the modal displays."""
    row = (
        Patient.objects.filter(id=patient_id)
        .values("id", "first_name", "last_name", "birth_date", "last_known_timezone")
        .first()
    )
    if not row:
        log.warning("scheduling context: patient %s not found", patient_id)
        return None
    return {
        "id": str(row["id"]),
        "full_name": f"{row['first_name']} {row['last_name']}".strip(),
        "dob": row["birth_date"].strftime("%m/%d/%Y") if row["birth_date"] else "",
        "timezone": row.get("last_known_timezone") or "",
    }


def _provider_prefill(staff_id: str) -> dict[str, str] | None:
    """Resolve a staff key into ``{id, name}``."""
    row = Staff.objects.filter(id=staff_id).values("id", "first_name", "last_name").first()
    if not row:
        log.warning("scheduling context: staff %s not found", staff_id)
        return None
    return {
        "id": str(row["id"]),
        "name": f"{row['first_name']} {row['last_name']}".strip(),
    }


def _location_prefill(location_id: str) -> dict[str, str] | None:
    """Resolve a practice location id into ``{id, name}``."""
    row = PracticeLocation.objects.filter(id=location_id).values("id", "full_name").first()
    if not row:
        log.warning("scheduling context: practice location %s not found", location_id)
        return None
    return {"id": str(row["id"]), "name": row["full_name"] or ""}


def reason_for_visit_for_note(note_id: str) -> str:
    """Return the reason-for-visit text currently on a note, or ``""``.

    Reads the ``reasonForVisit`` command's ``comment``. Takes the newest
    staged command, since editing a reason can leave older superseded rows.
    """
    row = (
        Command.objects.filter(
            note__id=note_id,
            schema_key=RFV_SCHEMA_KEY,
            state=RFV_ACTIVE_STATE,
        )
        .order_by("-created")
        .values("data")
        .first()
    )
    if not row:
        return ""
    return str((row["data"] or {}).get("comment") or "").strip()


def _appointment_prefill(appointment_id: str) -> dict[str, Any]:
    """Return the fields of an existing appointment worth carrying into the modal.

    Reschedule flows only hand over ``appointment`` (plus ``provider`` from the
    calendar), so everything else the form needs — visit type, location,
    duration, patient — has to come off the appointment itself.
    """
    appointment = (
        Appointment.objects.select_related("patient", "provider", "location", "note_type", "note")
        .filter(id=appointment_id)
        .first()
    )
    if appointment is None:
        log.warning("scheduling context: appointment %s not found", appointment_id)
        return {}

    resolved: dict[str, Any] = {}
    if appointment.patient:
        resolved["patient"] = _patient_prefill(str(appointment.patient.id))
    if appointment.provider:
        resolved["provider"] = {
            "id": str(appointment.provider.id),
            "name": f"{appointment.provider.first_name} {appointment.provider.last_name}".strip(),
        }
    if appointment.location:
        resolved["location"] = {
            "id": str(appointment.location.id),
            "name": appointment.location.full_name or "",
        }
    if appointment.note_type:
        resolved["note_type"] = {
            "id": str(appointment.note_type.id),
            "code": appointment.note_type.code or "",
            "name": appointment.note_type.name or "",
        }
    if appointment.duration_minutes:
        resolved["duration_minutes"] = int(appointment.duration_minutes)
    if appointment.note:
        resolved["note_id"] = str(appointment.note.id)
    return {key: value for key, value in resolved.items() if value}


def _calendar_local(
    moment: datetime.datetime,
    provider: dict[str, str] | None,
    location: dict[str, str] | None,
) -> datetime.datetime:
    """Express an instant as naive wall time in the booking calendar's timezone.

    Slots from ``/all-slots`` are naive datetimes in the calendar's own
    timezone, so a prefilled ``start`` can only be matched against them once
    it's expressed the same way. Without a provider there is no calendar to
    resolve, so the instant is left in UTC — good enough to land the calendar
    widget on the right day.
    """
    if moment.tzinfo is None:
        return moment.replace(microsecond=0)

    tz_name = "UTC"
    if provider:
        tz_name = get_location_timezone(provider["id"], location["name"] if location else "")
    try:
        tzinfo = ZoneInfo(tz_name)
    # ZoneInfoNotFoundError subclasses KeyError, and isn't importable in the
    # plugin sandbox; ValueError covers keys with path separators.
    except (KeyError, ValueError):
        log.warning("scheduling context: unknown timezone %r, falling back to UTC", tz_name)
        tzinfo = datetime.timezone.utc
    # Slot payloads carry whole seconds, so drop microseconds for a clean match.
    return moment.astimezone(tzinfo).replace(tzinfo=None, microsecond=0)


def build_prefill(query_params: dict) -> dict[str, Any]:
    """Build the modal prefill payload from ``/modal`` query params.

    Returns a JSON-serializable dict with any of:

    ``mode``, ``origin``, ``appointment_id``, ``note_id``, ``patient``,
    ``provider``, ``location``, ``note_type``, ``reason_for_visit``, ``start``
    (naive ISO in calendar time), ``date`` (``YYYY-MM-DD``), ``time``
    (``HH:MM``), ``duration_minutes``, ``lock_patient``.

    Keys whose value could not be resolved are omitted, so an empty context
    yields just the default ``mode``.
    """
    mode = _get(query_params, "mode") or DEFAULT_MODE
    if mode not in VALID_MODES:
        log.warning("scheduling context: unrecognized mode %r", mode)
        mode = DEFAULT_MODE

    appointment_id = _get(query_params, "appointment_id")
    from_appointment = _appointment_prefill(appointment_id) if appointment_id else {}

    patient_id = _get(query_params, "patient_id")
    provider_id = _get(query_params, "provider_id")
    location_id = _get(query_params, "location_id")

    # An explicitly-supplied entity wins; the appointment being rescheduled
    # backfills whatever the launching surface didn't send.
    patient = (_patient_prefill(patient_id) if patient_id else None) or from_appointment.get(
        "patient"
    )
    provider = (_provider_prefill(provider_id) if provider_id else None) or from_appointment.get(
        "provider"
    )
    location = (_location_prefill(location_id) if location_id else None) or from_appointment.get(
        "location"
    )
    note_type = from_appointment.get("note_type")

    # note_reschedule hands over the note directly; the other reschedule flows
    # only name the appointment, so fall back to the note hanging off it.
    note_id = _get(query_params, "note_id") or from_appointment.get("note_id", "")
    reason_for_visit = reason_for_visit_for_note(note_id) if note_id else ""

    start = _parse_iso(_get(query_params, "start"))
    end = _parse_iso(_get(query_params, "end"))
    # The slot length arrives as `duration` (reschedule flows) or `end`
    # (calendar drag-and-drop), never both, and neither from the schedule-page
    # and patient-chart buttons.
    duration_minutes = _positive_int(_get(query_params, "duration"))
    if duration_minutes is None and start and end:
        duration_minutes = _positive_int(int((end - start).total_seconds() // 60))
    if duration_minutes is None:
        duration_minutes = from_appointment.get("duration_minutes")

    prefill: dict[str, Any] = {
        "mode": mode,
        "origin": _get(query_params, "origin"),
        "appointment_id": appointment_id,
        "note_id": note_id,
        "patient": patient,
        "provider": provider,
        "location": location,
        "note_type": note_type,
        "reason_for_visit": reason_for_visit,
        "duration_minutes": duration_minutes,
    }

    if start:
        local_start = _calendar_local(start, provider, location)
        prefill["start"] = local_start.isoformat()
        prefill["date"] = local_start.date().isoformat()
        prefill["time"] = local_start.strftime("%H:%M")

    # The launching surface already fixed the patient, so the modal shouldn't
    # let the user swap it out from under a reschedule.
    prefill["lock_patient"] = bool(patient)

    return {key: value for key, value in prefill.items() if value not in (None, "")}


__all__ = (
    "ENTITY_PARAMS",
    "ASSET_VERSION",
    "MODAL_PATH",
    "ORIGIN_GLOBAL_PANEL",
    "RFV_ACTIVE_STATE",
    "RFV_SCHEMA_KEY",
    "SCALAR_PARAMS",
    "VALID_MODES",
    "build_prefill",
    "modal_url",
    "reason_for_visit_for_note",
)
