"""Wording for the task raised when a slot frees up.

Pure string building, so the exact text a scheduler reads can be checked
without a database or an effect.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from scheduling_waitlist.services.display import (
    ANY_LOCATION,
    ANY_PROVIDER,
    patient_name,
)
from scheduling_waitlist.services.slot import FreedSlot

TITLE_MAX = 140

HINT_DISCLAIMER = (
    "Preferred times above are a hint only; this plugin does not filter on them."
)
NO_BOOKING_NOTICE = (
    "Nobody has been booked. Schedule from the calendar as usual. The waitlist "
    "entry becomes 'scheduled' on its own once that patient has an appointment "
    "with a matching service, provider, and location."
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def format_slot_time(slot: FreedSlot, *, timezone_name: str) -> str:
    """The slot's start, in the practice's display timezone.

    The zone abbreviation is always printed. Practice locations carry no
    timezone of their own, so this is a single configured setting for the whole
    instance, and a wrong one has to be visible rather than silently shifting
    every time staff read.
    """
    if not isinstance(slot.start_time, datetime):
        return "Time unknown"

    try:
        zone = ZoneInfo(timezone_name or "UTC")
    except (KeyError, ValueError):
        zone = ZoneInfo("UTC")

    local = slot.start_time.astimezone(zone)
    # The hour is formatted by hand rather than with "%-I", which is a
    # platform extension rather than standard, so this reads the same wherever
    # the plugin runs.
    hour = local.hour % 12 or 12
    meridiem = "AM" if local.hour < 12 else "PM"
    label = (
        f"{local.strftime('%a %d %b %Y')}, {hour}:{local.strftime('%M')} "
        f"{meridiem} {local.strftime('%Z')}"
    ).strip()
    if slot.duration_minutes:
        label = f"{label} ({slot.duration_minutes} min)"
    return label


def compose_title(slot: FreedSlot, match_count: int, *, timezone_name: str) -> str:
    """One line naming the slot and how many patients fit it."""
    patients = "1 waitlisted patient" if match_count == 1 else f"{match_count} waitlisted patients"
    parts = [
        f"Slot opened - {patients} match",
        slot.note_type_label,
        format_slot_time(slot, timezone_name=timezone_name),
    ]
    if slot.provider_label:
        parts.append(slot.provider_label)
    title = " | ".join(part for part in parts if part)
    return title if len(title) <= TITLE_MAX else f"{title[: TITLE_MAX - 1]}…"


def _describe_window(entry: Any) -> str:
    note = getattr(entry, "preferred_window_note", "") or ""
    if note:
        return note

    windows = getattr(entry, "preferred_windows", None) or []
    if not windows:
        return "Any time"

    described = []
    for window in windows:
        days = ", ".join(
            _WEEKDAYS[day] for day in (window.get("days") or []) if 0 <= day < len(_WEEKDAYS)
        )
        start = window.get("start") or ""
        end = window.get("end") or ""
        span = f"{start}-{end}" if start and end else ""
        text = " ".join(part for part in (days, span) if part)
        if text:
            described.append(text)
    return "; ".join(described) or "Any time"


def _describe_wants(entry: Any) -> str:
    from scheduling_waitlist.constants import PREFERENCE_ANY
    from scheduling_waitlist.services.display import location_name, note_type_name, staff_name

    note_type = getattr(entry, "note_type", None)
    wants = [note_type_name(note_type) if note_type is not None else "Any service"]

    if getattr(entry, "provider_preference", "") == PREFERENCE_ANY:
        wants.append(ANY_PROVIDER)
    else:
        provider = getattr(entry, "desired_provider", None)
        wants.append(staff_name(provider) if provider is not None else ANY_PROVIDER)

    if getattr(entry, "location_preference", "") == PREFERENCE_ANY:
        wants.append(ANY_LOCATION)
    else:
        location = getattr(entry, "desired_location", None)
        wants.append(location_name(location) if location is not None else ANY_LOCATION)

    return " - ".join(wants)


def compose_body(
    slot: FreedSlot, entries: list[Any], *, timezone_name: str, today: Any = None
) -> str:
    """The task comment: the slot, then the matching patients in order."""
    from scheduling_waitlist.services.serializers import days_waiting

    lines = [
        f"Slot freed ({slot.source_event or 'appointment change'})",
        f"When:     {format_slot_time(slot, timezone_name=timezone_name)}",
        f"Service:  {slot.note_type_label}",
        f"Provider: {slot.provider_label}",
        f"Location: {slot.location_label}",
        "",
        "Matching waitlisted patients, most urgent first:",
        "",
    ]

    for index, entry in enumerate(entries, start=1):
        patient = getattr(entry, "patient", None)
        priority = getattr(entry, "priority_label", "") or "Unset"
        lines.append(f"{index}. [{priority}] {patient_name(patient)}")
        lines.append(f"   Wants: {_describe_wants(entry)}")
        lines.append(f"   Prefers: {_describe_window(entry)}")
        if today is not None:
            waited = days_waiting(getattr(entry, "created_at", None), today)
            lines.append(f"   Waiting {waited} day{'' if waited == 1 else 's'}")
        note = getattr(entry, "note", "") or ""
        if note:
            lines.append(f"   Note: {note}")
        lines.append("")

    lines.append(HINT_DISCLAIMER)
    lines.append(NO_BOOKING_NOTICE)
    return "\n".join(lines)
