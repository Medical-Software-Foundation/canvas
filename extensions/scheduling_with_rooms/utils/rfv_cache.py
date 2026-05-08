"""Transient cache for the booking-time Reason-for-Visit text.

The /book endpoint can't address the just-created Appointment by ID (it's
server-assigned), so it stashes the RFV text under a key derived from
(patient_id, provider_id, start_time_utc) and the APPOINTMENT_CREATED
handler reads it back out, originates the RFV command on the appointment's
note, and clears the entry.
"""

from __future__ import annotations

import datetime

from canvas_sdk.caching.plugins import get_cache
from logger import log

_TTL_SECONDS = 600  # 10 minutes — APPOINTMENT_CREATED fires nearly instantly


def _normalize_dt(dt: datetime.datetime) -> str:
    """Render a datetime as a UTC ISO string for stable cache keys."""
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC; both sides produce naive-UTC equally.
        return dt.replace(microsecond=0).isoformat()
    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()


def make_key(patient_id: str, provider_id: str, start_time: datetime.datetime) -> str:
    return f"rc:rfv:{patient_id}:{provider_id}:{_normalize_dt(start_time)}"


def stash(patient_id: str, provider_id: str, start_time: datetime.datetime, text: str) -> None:
    if not text:
        return
    key = make_key(patient_id, provider_id, start_time)
    get_cache().set(key, text, timeout_seconds=_TTL_SECONDS)
    log.info("rfv-cache: stash key=%r start_time=%r text=%r", key, start_time, text)


def pop(patient_id: str, provider_id: str, start_time: datetime.datetime) -> str:
    """Return and clear the stashed RFV text, or '' if missing."""
    key = make_key(patient_id, provider_id, start_time)
    cache = get_cache()
    value = cache.get(key)
    log.info(
        "rfv-cache: pop key=%r start_time=%r found=%s",
        key, start_time, value is not None,
    )
    if value is None:
        return ""
    cache.delete(key)
    return value if isinstance(value, str) else ""
