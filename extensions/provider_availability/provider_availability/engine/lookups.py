"""Lookup helpers for populating admin UI dropdowns."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data import NoteType, PracticeLocation, Staff
from canvas_sdk.v1.data.team import Team
from logger import log


def get_active_providers() -> list[dict[str, Any]]:
    """Return active staff in a schedulable role, sorted by last name.

    "Schedulable" is configurable per practice by StaffRole internal code (see
    ``engine.roles``); until configured, it is every staff member with a
    Provider role type.
    """
    from provider_availability.engine.roles import get_schedulable_staff

    results: list[dict[str, Any]] = []
    for staff in get_schedulable_staff():
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


def get_active_staff_ids() -> set[str]:
    """Return the set of all active staff UUIDs (not just providers).

    Availability can be scheduled for any active staff record, so the CSV
    importer keys on the staff UUID rather than NPI (which only providers have).
    """
    ids = {str(i) for i in Staff.objects.filter(active=True).values_list("id", flat=True)}
    log.info("get_active_staff_ids: found %d active staff", len(ids))
    return ids


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


def get_staff_directory() -> list[dict[str, Any]]:
    """Active staff for the editing-group pickers, with each person's primary location.

    ``location_id`` drives the group form's "Add everyone at" quick add. Sorted
    by last name, like the provider lists.
    """
    rows = (
        Staff.objects.filter(active=True)
        .values_list("id", "first_name", "last_name", "primary_practice_location__id")
    )
    people: list[tuple[tuple[str, str], dict[str, Any]]] = []
    for sid, first, last, loc_id in rows:
        sort_key = ((last or "").strip().lower(), (first or "").strip().lower())
        people.append((sort_key, {
            "id": str(sid),
            "name": f"{first or ''} {last or ''}".strip(),
            "location_id": str(loc_id) if loc_id else "",
        }))
    people.sort(key=lambda pair: pair[0])
    results = [person for _, person in people]
    log.info("get_staff_directory: found %d active staff", len(results))
    return results


def get_teams() -> list[dict[str, Any]]:
    """Canvas teams, for picking the admin team. Sorted by name."""
    results = [{"id": str(tid), "name": name or ""} for tid, name in Team.objects.values_list("id", "name")]
    results.sort(key=lambda t: t["name"].lower())
    return results
