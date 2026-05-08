"""Transient cache for the booking-time RR room ScheduleEvent intent.

The /book endpoint can't address the just-created Appointment by ID (it's
server-assigned), so it stashes the room booking intent under a key derived
from (patient_id, provider_id, start_time_utc) and the APPOINTMENT_CREATED
handler reads it back out, creates the ScheduleEvent on the RR staff
member's calendar with ``parent_appointment_id`` pointing at the patient
Appointment, and clears the entry.
"""

from __future__ import annotations

import datetime

from canvas_sdk.caching.plugins import get_cache

_TTL_SECONDS = 600  # 10 minutes — APPOINTMENT_CREATED fires nearly instantly


def _normalize_dt(dt: datetime.datetime) -> str:
    """Render a datetime as a UTC ISO string for stable cache keys."""
    if dt.tzinfo is None:
        return dt.replace(microsecond=0).isoformat()
    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def make_key(patient_id: str, provider_id: str, start_time: datetime.datetime) -> str:
    return f"rc:rr:{patient_id}:{provider_id}:{_normalize_dt(start_time)}"


def stash(
    patient_id: str,
    provider_id: str,
    start_time: datetime.datetime,
    *,
    rr_staff_id: str,
    note_type_id: str,
    duration_minutes: int,
    location_id: str,
    description: str = "",
) -> None:
    key = make_key(patient_id, provider_id, start_time)
    get_cache().set(
        key,
        {
            "rr_staff_id": rr_staff_id,
            "note_type_id": note_type_id,
            "duration_minutes": duration_minutes,
            "location_id": location_id,
            "description": description,
        },
        timeout_seconds=_TTL_SECONDS,
    )


def pop(patient_id: str, provider_id: str, start_time: datetime.datetime) -> dict | None:
    """Return and clear the stashed RR booking intent, or None if missing."""
    key = make_key(patient_id, provider_id, start_time)
    cache = get_cache()
    value = cache.get(key)
    if value is None:
        return None
    cache.delete(key)
    return value if isinstance(value, dict) else None
