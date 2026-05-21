"""Lookup helpers for populating admin UI dropdowns."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import NoteType, PracticeLocation, Staff
from logger import log


def get_active_providers() -> list[dict[str, Any]]:
    """Return all active staff with PROVIDER role, sorted by last name."""
    results: list[dict[str, Any]] = []
    for staff in Staff.objects.filter(active=True, roles__role_type="PROVIDER").distinct():
        results.append(
            {
                "id": str(staff.id),
                "name": f"{staff.first_name} {staff.last_name}".strip(),
                "npi_number": staff.npi_number or "",
                "_sort_key": (staff.last_name or "").strip().lower(),
            }
        )
    results.sort(key=lambda p: p["_sort_key"])
    for p in results:
        del p["_sort_key"]
    log.info("get_active_providers: found %d providers", len(results))
    return results


def get_active_locations() -> list[dict[str, Any]]:
    """Return all active practice locations for the location dropdown."""
    results: list[dict[str, Any]] = []
    for loc in PracticeLocation.objects.filter(active=True):
        results.append(
            {
                "id": str(loc.id),
                "name": loc.full_name or loc.short_name or "",
            }
        )
    results.sort(key=lambda loc: loc["name"].lower())
    log.info("get_active_locations: found %d locations", len(results))
    return results


def get_scheduleable_visit_types() -> list[dict[str, Any]]:
    """Return scheduleable and schedule-event note types for the visit type dropdown."""
    seen: set[str] = set()
    results: list[dict[str, Any]] = []

    scheduleable = NoteType.objects.filter(is_active=True, is_scheduleable=True)
    for nt in scheduleable:
        nt_id = str(nt.id)
        if nt_id not in seen:
            seen.add(nt_id)
            results.append({"id": nt_id, "name": nt.name or ""})

    schedule_events = NoteType.objects.filter(
        is_active=True, category="schedule_event"
    )
    for nt in schedule_events:
        nt_id = str(nt.id)
        if nt_id not in seen:
            seen.add(nt_id)
            results.append({"id": nt_id, "name": nt.name or ""})

    results.sort(key=lambda vt: vt["name"].lower())
    log.info("get_scheduleable_visit_types: found %d types", len(results))
    return results
