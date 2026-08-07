"""Builds the choices offered on the waitlist form and the roster filters.

Appointment types, providers, and locations are read from the instance rather
than listed in configuration, so the plugin carries no practice-specific names
and works on a fresh install with nothing configured. The appointment-type
secret narrows that list; it does not define it.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import NoteType, PracticeLocation, Staff

from scheduling_waitlist.constants import (
    PREFERENCE_ANY,
    STATUS_EXPIRED,
    STATUS_OFFERED,
    STATUS_REMOVED,
    STATUS_SCHEDULED,
    STATUS_WAITING,
)
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.display import location_name, staff_name

# Fixed vocabulary. Stored on the entry, displayed on the task, and matched on
# only when the practice turns window enforcement on.
TIME_WINDOWS: tuple[dict[str, Any], ...] = (
    {"value": "any", "label": "Any time", "days": [], "start": "", "end": ""},
    {
        "value": "weekday_am",
        "label": "Weekday mornings",
        "days": [0, 1, 2, 3, 4],
        "start": "08:00",
        "end": "12:00",
    },
    {
        "value": "weekday_pm",
        "label": "Weekday afternoons",
        "days": [0, 1, 2, 3, 4],
        "start": "12:00",
        "end": "17:00",
    },
    {
        "value": "weekend",
        "label": "Weekends",
        "days": [5, 6],
        "start": "08:00",
        "end": "17:00",
    },
)

STATUS_LABELS: tuple[tuple[str, str], ...] = (
    (STATUS_WAITING, "Waiting"),
    (STATUS_OFFERED, "Offered"),
    (STATUS_SCHEDULED, "Scheduled"),
    (STATUS_REMOVED, "Removed"),
    (STATUS_EXPIRED, "Expired"),
)


def time_window_by_value(value: str) -> dict[str, Any] | None:
    """Look up a window in the fixed vocabulary."""
    for window in TIME_WINDOWS:
        if window["value"] == value:
            return window
    return None


def windows_for_value(value: str) -> list[dict[str, Any]]:
    """The structured form stored on an entry for a chosen window.

    "Any time" stores nothing, which keeps the common case cheap to match and
    means an entry with no stored window is never accidentally filtered out.
    """
    window = time_window_by_value(value)
    if window is None or not window["days"]:
        return []
    return [{"days": list(window["days"]), "start": window["start"], "end": window["end"]}]


def list_appointment_types(config: WaitlistConfig) -> list[dict[str, Any]]:
    """Bookable appointment types, optionally narrowed by configuration.

    Only types that can actually be scheduled are offered: a waitlist entry for
    something nobody can book is a dead row.
    """
    note_types = NoteType.objects.filter(
        is_scheduleable=True,
        is_active=True,
        is_visible=True,
        deprecated_at__isnull=True,
    ).order_by("name")

    allowed = {code.casefold() for code in config.appointment_type_codes}

    options = []
    for note_type in note_types:
        code = (getattr(note_type, "code", "") or "").strip()
        if allowed and code.casefold() not in allowed:
            continue
        options.append(
            {
                "dbid": getattr(note_type, "dbid", None),
                "code": code,
                "name": (getattr(note_type, "name", "") or "").strip() or code,
            }
        )
    return options


def list_providers() -> list[dict[str, Any]]:
    """Active staff who can be requested by name."""
    return [
        {"dbid": getattr(staff, "dbid", None), "name": staff_name(staff)}
        for staff in Staff.objects.filter(active=True).order_by("last_name", "first_name")
    ]


def list_locations() -> list[dict[str, Any]]:
    """Active practice locations."""
    return [
        {"dbid": getattr(location, "dbid", None), "name": location_name(location)}
        for location in PracticeLocation.objects.filter(active=True).order_by("full_name")
    ]


def list_priorities(config: WaitlistConfig) -> list[dict[str, Any]]:
    """Configured priority labels, most urgent first."""
    return [
        {"label": label, "rank": rank}
        for rank, label in enumerate(config.priority_labels)
    ]


def build_options(config: WaitlistConfig) -> dict[str, Any]:
    """Everything the form and the filter bar need, in one payload."""
    return {
        "appointment_types": list_appointment_types(config),
        "providers": list_providers(),
        "locations": list_locations(),
        "priorities": list_priorities(config),
        "time_windows": [
            {"value": window["value"], "label": window["label"]} for window in TIME_WINDOWS
        ],
        "statuses": [{"value": value, "label": label} for value, label in STATUS_LABELS],
        "any_preference": PREFERENCE_ANY,
        # Surfaced so the form can explain why creation is refused rather than
        # presenting an empty dropdown with no reason.
        "is_configured": bool(config.appointment_type_codes),
    }
