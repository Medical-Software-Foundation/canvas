"""Translate a Canvas appointment into a Google Calendar event body — PHI-safe by construction.

Compliance rule (spec §7): **no patient identifiers in any Google event field.** The only
patient-controllable free text on a Canvas appointment (``comment``/``description``) is therefore
*never* copied. The event title is the visit type (the same generic value the ICS feeds already
publish), the location is the practice-location short name, and the description carries only a
meeting link. There is no patient name, DOB, MRN, or clinical detail anywhere in the payload.

This module is intentionally free of SDK and network imports so the mapping and the echo-suppression
hash can be unit-tested as pure functions.
"""

import json
from datetime import datetime
from hashlib import sha256
from typing import TypedDict

import arrow

# Every event we write is stamped with this so an inbound webhook delta can tell our own writes apart
# from genuine provider edits (spec §6.1).
CANVAS_APPT_ID_KEY = "canvasApptId"

# Canvas appointment progress status -> Google event status.
_STATUS_MAP = {
    "unconfirmed": "tentative",
    "attempted": "tentative",
    "confirmed": "confirmed",
    "arrived": "confirmed",
    "roomed": "confirmed",
    "exited": "confirmed",
    "noshowed": "cancelled",
    "cancelled": "cancelled",
}


class AppointmentSnapshot(TypedDict):
    """The non-PHI fields the handler reads off an ``Appointment`` to build an event.

    ``start_time`` is a timezone-aware datetime; ``visit_type`` is the note type's display string
    (e.g. "Office Visit"), never patient text.
    """

    appointment_id: str
    visit_type: str | None
    start_time: datetime
    duration_minutes: int
    location: str | None
    meeting_link: str | None
    status: str | None


def _format_rfc3339(value: datetime | str) -> str:
    """Render a datetime (or parseable string) as a UTC RFC3339 timestamp Google accepts."""
    return arrow.get(value).to("UTC").format("YYYY-MM-DD[T]HH:mm:ss[Z]")


def google_status(canvas_status: str | None) -> str:
    """Map a Canvas progress status to a Google event status, defaulting to ``tentative``."""
    return _STATUS_MAP.get(canvas_status or "", "tentative")


def build_event_body(appt: AppointmentSnapshot) -> dict:
    """Build the Google Calendar event resource for an appointment.

    The returned dict is safe to pass straight to ``events.insert``/``events.update``. It contains no
    PHI: title is the visit type, description is the meeting link (if any), and the appointment id is
    stored in a private extended property for echo detection and reverse lookup.
    """
    start = _format_rfc3339(appt["start_time"])
    end = _format_rfc3339(
        arrow.get(appt["start_time"]).shift(minutes=int(appt["duration_minutes"])).datetime
    )

    body: dict = {
        "summary": appt.get("visit_type") or "Appointment",
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "status": google_status(appt.get("status")),
        "extendedProperties": {"private": {CANVAS_APPT_ID_KEY: str(appt["appointment_id"])}},
    }

    location = appt.get("location")
    if location:
        body["location"] = location

    # The telehealth / meeting link is the one piece of per-appointment context providers want in
    # their calendar. It is resolved per event (appointment link, else the provider's telehealth
    # room) before it reaches here, and is the only thing placed in the description. A "Join:" label
    # keeps it obvious while Google still auto-links the bare URL on its own line.
    meeting_link = appt.get("meeting_link")
    if meeting_link:
        body["description"] = f"Join:\n{meeting_link}"

    return body


def content_hash(body: dict) -> str:
    """Stable hash of the Canvas-controlled semantic fields of an event body.

    Used for echo suppression: we store this when we push, then compare it against the hash of an
    inbound event to decide whether a webhook delta is our own write coming back. Volatile/server
    fields (etag, updated, sequence) are excluded so the hash only moves when *content* changes.
    """
    material = {
        "summary": body.get("summary"),
        "location": body.get("location"),
        "description": body.get("description"),
        "start": body.get("start"),
        "end": body.get("end"),
        "status": body.get("status"),
    }
    # sort_keys gives a deterministic serialization regardless of dict insertion order.
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def extract_canvas_appt_id(event: dict) -> str | None:
    """Pull the stamped Canvas appointment id back out of a Google event, if present."""
    private = (event.get("extendedProperties") or {}).get("private", {})
    value = private.get(CANVAS_APPT_ID_KEY)
    return str(value) if value is not None else None


def _normalize_time_field(field: dict | None) -> dict | None:
    """Normalize a Google ``start``/``end`` block to the same shape :func:`build_event_body` emits.

    Google may echo a timed event's ``dateTime`` with a zone offset (``...-04:00``) rather than the
    ``Z`` form we sent; normalizing to UTC ``Z`` means the same instant hashes identically.
    """
    if not field:
        return None
    raw = field.get("dateTime") or field.get("date")
    if not raw:
        return None
    return {"dateTime": _format_rfc3339(raw), "timeZone": "UTC"}


def google_event_content_hash(event: dict) -> str:
    """Compute the echo-suppression hash of an *inbound* Google event.

    Reshapes the Google event resource into the same material :func:`build_event_body` produces so the
    result can be compared against the stored ``last_pushed_hash`` to detect our own write bouncing
    back through the watch channel (spec §6.1).
    """
    reshaped = {
        "summary": event.get("summary"),
        "location": event.get("location"),
        "description": event.get("description"),
        "start": _normalize_time_field(event.get("start")),
        "end": _normalize_time_field(event.get("end")),
        "status": event.get("status"),
    }
    return content_hash(reshaped)
