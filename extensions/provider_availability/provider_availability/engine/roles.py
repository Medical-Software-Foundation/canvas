"""Configurable schedulable-role logic.

Which staff are "schedulable" — get a Clinic calendar, appear in the provider
dropdown, and are provisioned — is configurable per practice by StaffRole
``internal_code``. A staff member qualifies if ANY of their roles' internal
code is in the configured set.

We scan every role (``staff.roles.all()``) rather than
``Staff.top_role_abbreviation`` on purpose: that SDK property is derived only
from *clinical* roles, so a purely administrative staff member has no top role
and could never be scheduled. Matching on ``internal_code`` (always populated,
unlike ``public_abbreviation`` which is blank for most non-clinical roles) lets
a practice schedule non-clinical staff such as Care Coordinators or Office
Managers.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.staff import Staff, StaffRole
from logger import log

from provider_availability.engine.storage import get_schedulable_roles


def _normalize(code: str) -> str:
    """Normalize an internal code for case-insensitive comparison."""
    return (code or "").strip().upper()


def get_schedulable_codes() -> set[str]:
    """Return the configured schedulable internal codes, normalized."""
    return {_normalize(c) for c in get_schedulable_roles() if _normalize(c)}


def is_schedulable_staff(staff: Staff, schedulable_codes: set[str]) -> bool:
    """Return True if any of the staff member's roles is a schedulable role.

    Scans all roles so administrative/hybrid roles count too, not just the top
    clinical role. ``schedulable_codes`` must already be normalized (upper-cased).
    """
    for role in staff.roles.all():
        if _normalize(role.internal_code) in schedulable_codes:
            return True
    return False


def get_schedulable_staff() -> list[Staff]:
    """Return active staff whose role set makes them schedulable.

    Prefetches roles to avoid an N+1 across the per-staff ``is_schedulable_staff``
    check.
    """
    codes = get_schedulable_codes()
    if not codes:
        log.info("get_schedulable_staff: no schedulable roles configured")
        return []
    staff = Staff.objects.filter(active=True).prefetch_related("roles")
    result = [s for s in staff if is_schedulable_staff(s, codes)]
    log.info("get_schedulable_staff: %d of active staff are schedulable", len(result))
    return result


def get_available_roles() -> list[dict[str, Any]]:
    """Return the distinct roles held by active staff, for the Settings UI.

    Aggregated by ``internal_code`` with a staff count so the practice can see
    which roles exist and how many people hold each. Roles with a blank internal
    code are skipped (they can never be matched).
    """
    agg: dict[str, dict[str, Any]] = {}
    for role in StaffRole.objects.filter(staff__active=True):
        code = _normalize(role.internal_code)
        if not code:
            continue
        entry = agg.get(code)
        if entry is None:
            entry = {
                "code": code,
                "name": role.name or "",
                "abbreviation": role.public_abbreviation or "",
                "domain": role.domain or "",
                "_staff_ids": set(),
            }
            agg[code] = entry
        # role.staff_id is the already-loaded FK column — no extra query.
        entry["_staff_ids"].add(role.staff_id)

    results: list[dict[str, Any]] = []
    for entry in agg.values():
        results.append(
            {
                "code": entry["code"],
                "name": entry["name"],
                "abbreviation": entry["abbreviation"],
                "domain": entry["domain"],
                "staff_count": len(entry["_staff_ids"]),
            }
        )
    results.sort(key=lambda r: (-r["staff_count"], r["code"]))
    log.info("get_available_roles: found %d distinct roles", len(results))
    return results
