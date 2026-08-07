"""Turning waitlist entries into the JSON the roster and forms consume."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from scheduling_waitlist.constants import PREFERENCE_ANY
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.display import (
    ANY_LOCATION,
    ANY_PROVIDER,
    ANY_TYPE,
    location_name,
    note_type_name,
    patient_name,
    staff_name,
)
from scheduling_waitlist.services.permissions import can_modify_entry


def _as_date(value: Any) -> date | None:
    """Coerce a date or datetime to a date, tolerating anything else."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def days_waiting(created_at: Any, today: date) -> int:
    """Whole days between an entry being added and today.

    Never negative: a clock skew that puts creation in the future should read as
    "added today", not as a negative wait that sorts strangely.
    """
    created = _as_date(created_at)
    if created is None:
        return 0
    return max((today - created).days, 0)


def is_past_shelf_life(expires_on: Any, today: date) -> bool:
    """Whether an entry has outlived its configured shelf life.

    ``expires_on`` is the last day an entry stays valid, so an entry is still
    live on that date and lapses the day after. An entry with no expiry date --
    which happens because the schema pipeline emits no column defaults -- never
    lapses on its own.
    """
    expiry = _as_date(expires_on)
    if expiry is None:
        return False
    return today > expiry


def serialize_entry(
    entry: Any,
    *,
    config: WaitlistConfig,
    today: date,
    viewer: Any | None = None,
    manages_all: bool = False,
) -> dict[str, Any]:
    """One roster row.

    Reads the related patient, type, provider, and location, so the queryset
    that produced ``entry`` must have selected them; otherwise this is four
    extra queries per row.
    """
    prefers_any_provider = getattr(entry, "provider_preference", "") == PREFERENCE_ANY
    prefers_any_location = getattr(entry, "location_preference", "") == PREFERENCE_ANY

    note_type = getattr(entry, "note_type", None)
    provider = getattr(entry, "desired_provider", None)
    location = getattr(entry, "desired_location", None)
    patient = getattr(entry, "patient", None)
    creator = getattr(entry, "created_by", None)

    priority_label = getattr(entry, "priority_label", "") or ""
    expires_on = getattr(entry, "expires_on", None)

    can_modify = can_modify_entry(entry, viewer, manages_all)

    return {
        "dbid": getattr(entry, "dbid", None),
        "patient": {
            "id": getattr(patient, "id", None),
            "dbid": getattr(entry, "patient_id", None),
            "name": patient_name(patient),
        },
        "appointment_type": {
            "dbid": getattr(entry, "note_type_id", None),
            "name": note_type_name(note_type) if note_type is not None else ANY_TYPE,
        },
        "provider": {
            "dbid": None if prefers_any_provider else getattr(entry, "desired_provider_id", None),
            "name": ANY_PROVIDER if prefers_any_provider else staff_name(provider),
            "is_any": prefers_any_provider,
        },
        "location": {
            "dbid": None if prefers_any_location else getattr(entry, "desired_location_id", None),
            "name": ANY_LOCATION if prefers_any_location else location_name(location),
            "is_any": prefers_any_location,
        },
        "priority": {
            "label": priority_label,
            "rank": getattr(entry, "priority_rank", 0) or 0,
            "is_known": config.is_known_priority(priority_label),
        },
        "preferred_window": {
            "windows": getattr(entry, "preferred_windows", None) or [],
            "timezone": getattr(entry, "preferred_windows_timezone", "") or "",
            "note": getattr(entry, "preferred_window_note", "") or "",
        },
        # Never null: the roster puts this straight into a table cell.
        "note": getattr(entry, "note", "") or "",
        "status": getattr(entry, "status", "") or "",
        "status_reason": getattr(entry, "status_reason", "") or "",
        "created_at": _iso(getattr(entry, "created_at", None)),
        "created_by": {
            "dbid": getattr(entry, "created_by_id", None),
            "name": staff_name(creator) if creator is not None else "",
        },
        "days_waiting": days_waiting(getattr(entry, "created_at", None), today),
        "expires_on": _iso(expires_on),
        "is_past_shelf_life": is_past_shelf_life(expires_on, today),
        "can_edit": can_modify,
        "can_remove": can_modify,
    }


def _iso(value: Any) -> str:
    """ISO 8601 for a date or datetime, empty string for anything else."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return ""
