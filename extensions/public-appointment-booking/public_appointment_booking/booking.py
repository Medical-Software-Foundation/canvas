"""Slot listing, slot holds and patient matching for public booking.

Slot search itself lives in `slot_search.py` (copied from the MSF
urgent-care-self-scheduler plugin; plugins cannot import each other).
"""

import datetime
from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

from public_appointment_booking.slot_search import (
    find_available_slots,
    resolve_urgent_care_note_type,
)

# Public slot fields. Everything else the slot search returns stays server-side.
PUBLIC_SLOT_FIELDS = (
    "provider_id",
    "provider_name",
    "start_iso",
    "end_iso",
    "location_name",
)

SLOTS_CACHE_KEY = "public_slots:v1"
SLOTS_CACHE_SECONDS = 60
HOLD_KEY_PREFIX = "hold:"
MAX_CACHE_SECONDS = 14 * 24 * 3600  # plugin cache TTL ceiling


def _resolve_timezone(tz_string: str | None) -> ZoneInfo:
    if not tz_string:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_string)
    except (KeyError, ValueError):
        return ZoneInfo("UTC")


def active_location() -> tuple[str | None, ZoneInfo]:
    """(id, timezone) of the first active practice location, or (None, UTC)."""
    from canvas_sdk.v1.data.practicelocation import (
        PracticeLocation,
        PracticeLocationSetting,
    )

    location = PracticeLocation.objects.filter(active=True).first()
    if not location:
        return None, ZoneInfo("UTC")
    setting = PracticeLocationSetting.objects.filter(
        practice_location=location, name="last_known_timezone"
    ).first()
    return str(location.id), _resolve_timezone(setting.value if setting else None)


def location_index() -> dict[str, tuple[str, str]]:
    """Maps active PracticeLocation full_name to (id, display name); drops duplicate names."""
    from canvas_sdk.v1.data.practicelocation import PracticeLocation

    index: dict[str, tuple[str, str]] = {}
    ambiguous: set[str] = set()
    for location in PracticeLocation.objects.filter(active=True):
        if location.full_name in index:
            ambiguous.add(location.full_name)
        index[location.full_name] = (
            str(location.id),
            location.short_name or location.full_name,
        )
    for name in ambiguous:
        index.pop(name, None)
    return index


def hold_key(provider_id: str, start: datetime.datetime) -> str:
    """Cache key for a held slot, by provider and absolute start instant."""
    instant = start.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{HOLD_KEY_PREFIX}{provider_id}:{instant}"


def hold_seconds(start: datetime.datetime, now: datetime.datetime) -> int:
    """How long to hold a slot: until an hour after it starts, within the cache ceiling."""
    seconds = int((start - now).total_seconds()) + 3600
    return max(60, min(seconds, MAX_CACHE_SECONDS))


def search_slots(
    *, note_type: Any, note_type_name: str, now: datetime.datetime, lead: int, days: int
) -> list[dict]:
    """Raw slot search (all fields) over the booking window."""
    _, practice_tz = active_location()
    return find_available_slots(
        note_type_name=note_type_name,
        window_start=now,
        window_end=now + datetime.timedelta(days=days),
        practice_timezone=practice_tz,
        now=now,
        lead_time_minutes=lead,
        note_type=note_type,
        location_index=location_index(),
    )


def drop_held(slots: list[dict], cache: Any) -> list[dict]:
    """Removes slots someone has already requested through this plugin."""
    if not slots:
        return []
    keys = {
        id(s): hold_key(
            s["provider_id"], datetime.datetime.fromisoformat(s["start_iso"])
        )
        for s in slots
    }
    held = cache.get_many(list(keys.values()))
    return [s for s in slots if keys[id(s)] not in held]


def public_slot(slot: dict, duration_minutes: int) -> dict:
    """Projects a slot onto the fields that are safe to return publicly."""
    out = {field: slot.get(field) for field in PUBLIC_SLOT_FIELDS}
    out["duration_minutes"] = duration_minutes
    return out


def resolve_note_type(note_type_name: str) -> Any:
    """The configured scheduleable NoteType, or None."""
    return resolve_urgent_care_note_type(note_type_name)


def find_matching_patient(
    *,
    first_name: str,
    last_name: str,
    birth_date: datetime.date,
    email: str,
    phone: str,
) -> Any:
    """The single active patient matching name + birth date + (email or phone), else None.

    Returns None when zero or several patients match, so an ambiguous match never
    books onto the wrong chart. The caller must not reveal which case happened.
    """
    from canvas_sdk.v1.data.patient import Patient

    candidates = list(
        Patient.objects.filter(
            first_name__iexact=first_name,
            last_name__iexact=last_name,
            birth_date=birth_date,
            active=True,
        ).prefetch_related("telecom")[:5]
    )
    matches = []
    for patient in candidates:
        for contact in patient.telecom.all():
            if contact.state == "deleted":
                continue
            value = (contact.value or "").strip()
            if contact.system == "email" and value.lower() == email:
                matches.append(patient)
                break
            if contact.system == "phone" and value and _digits(value)[-10:] == phone:
                matches.append(patient)
                break
    return matches[0] if len(matches) == 1 else None


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())
