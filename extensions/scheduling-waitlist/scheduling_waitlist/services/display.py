"""Turning records into strings a person can read.

Every helper here returns a usable string for a missing or half-populated
record. Rendering a bare "None" into a roster row or a task body is a small bug
that looks like a broken plugin.
"""

from __future__ import annotations

from typing import Any

UNNAMED_STAFF = "Unnamed staff member"
UNNAMED_LOCATION = "Unnamed location"
UNNAMED_PATIENT = "Unnamed patient"
UNSPECIFIED = "Unspecified"
ANY_PROVIDER = "Any provider"
ANY_LOCATION = "Any location"
ANY_TYPE = "Any appointment type"


def _joined_name(record: Any, fallback: str) -> str:
    first = (getattr(record, "first_name", "") or "").strip()
    last = (getattr(record, "last_name", "") or "").strip()
    full = f"{first} {last}".strip()
    return full or fallback


def staff_name(staff: Any | None) -> str:
    """A staff member's display name."""
    if staff is None:
        return UNNAMED_STAFF
    return _joined_name(staff, UNNAMED_STAFF)


def patient_name(patient: Any | None) -> str:
    """A patient's display name."""
    if patient is None:
        return UNNAMED_PATIENT
    return _joined_name(patient, UNNAMED_PATIENT)


def location_name(location: Any | None) -> str:
    """A practice location's display name, preferring the full name."""
    if location is None:
        return UNNAMED_LOCATION
    full = (getattr(location, "full_name", "") or "").strip()
    short = (getattr(location, "short_name", "") or "").strip()
    return full or short or UNNAMED_LOCATION


def note_type_name(note_type: Any | None) -> str:
    """An appointment type's display name, falling back to its code."""
    if note_type is None:
        return UNSPECIFIED
    name = (getattr(note_type, "name", "") or "").strip()
    code = (getattr(note_type, "code", "") or "").strip()
    return name or code or UNSPECIFIED
