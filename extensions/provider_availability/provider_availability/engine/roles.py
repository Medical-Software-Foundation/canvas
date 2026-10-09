"""Configurable schedulable-role logic.

Which staff are "schedulable" — get a Clinic calendar, appear in the provider
dropdown, and are provisioned — is configurable per practice by StaffRole
``internal_code``. A staff member qualifies if ANY of their roles' internal
code is in the configured set. Until a practice configures a set, every staff
member holding a role whose ``role_type`` is Provider qualifies, matching the
plugin's behavior before roles were configurable.

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


PROVIDER_ROLE_TYPE = "PROVIDER"


def get_schedulable_codes() -> set[str] | None:
    """Return the configured schedulable internal codes, normalized.

    None means roles were never configured, so the Provider role type decides.
    """
    configured = get_schedulable_roles()
    if configured is None:
        return None
    return {_normalize(c) for c in configured if _normalize(c)}


def is_schedulable_staff(staff: Staff, schedulable_codes: set[str] | None) -> bool:
    """Return True if any of the staff member's roles is a schedulable role.

    Scans all roles so administrative/hybrid roles count too, not just the top
    clinical role. ``schedulable_codes`` must already be normalized (upper-cased);
    None means any role with the Provider role type qualifies.
    """
    for role in staff.roles.all():
        if schedulable_codes is None:
            if role.role_type == PROVIDER_ROLE_TYPE:
                return True
        elif _normalize(role.internal_code) in schedulable_codes:
            return True
    return False


def get_schedulable_staff() -> list[Staff]:
    """Return active staff whose role set makes them schedulable.

    A configured set that matches no active staff falls back to the Provider
    role type rather than making nobody bookable. Every caller (slot search,
    pickers, overview, calendar sync) then agrees, and a configuration that
    has drifted out of date cannot clear a practice's availability.

    Prefetches roles to avoid an N+1 across the per-staff ``is_schedulable_staff``
    check.
    """
    codes = get_schedulable_codes()
    # Only the fields callers read (key, name, NPI); roles are prefetched for the role check.
    staff = list(
        Staff.objects.filter(active=True)
        .only("id", "first_name", "last_name", "npi_number")
        .prefetch_related("roles")
    )
    result = [s for s in staff if is_schedulable_staff(s, codes)]
    if codes is not None and not result:
        log.warning(
            "get_schedulable_staff: configured roles %s match no active staff, "
            "falling back to the Provider role type",
            sorted(codes),
        )
        result = [s for s in staff if is_schedulable_staff(s, None)]
    log.info("get_schedulable_staff: %d of active staff are schedulable", len(result))
    return result


def is_provider_type_fallback_active() -> bool:
    """True when saved roles exist but no active staff member holds one, so the
    Provider role type is deciding who is bookable instead."""
    codes = get_schedulable_codes()
    if codes is None:
        return False
    staff = Staff.objects.filter(active=True).only("id").prefetch_related("roles")
    return not any(is_schedulable_staff(s, codes) for s in staff)


def get_effective_schedulable_roles() -> list[str]:
    """The role codes currently deciding who is schedulable, for display.

    When roles were never configured, these are the codes of the Provider-type
    roles held by active staff, so the Settings tab shows what is in effect
    rather than an empty selection.
    """
    configured = get_schedulable_roles()
    if configured is not None:
        return configured
    codes = {
        _normalize(role.internal_code)
        for role in StaffRole.objects.filter(staff__active=True, role_type=PROVIDER_ROLE_TYPE)
    }
    return sorted(c for c in codes if c)


def get_schedulable_provider_ids() -> set[str]:
    """Return the set of currently-schedulable staff ids (as strings).

    Used to gate availability effectiveness: a provider not in this set must
    not generate bookable slots or calendar availability events.
    """
    return {str(s.id) for s in get_schedulable_staff()}


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
