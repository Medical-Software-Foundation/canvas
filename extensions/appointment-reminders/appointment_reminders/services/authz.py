"""Role gate for the appointment-reminders admin surfaces.

``StaffSessionAuthMixin`` proves only that the caller is *some* logged-in staff
member — its own docstring says it "only cares that they are a staff, with no
regard to roles". Without a second check, any staff account could rewrite every
campaign template or switch live sending on, whether or not the provider-menu
item is in front of them.

Role names are configured per instance, so the allowed set is a secret rather
than a constant. Fails closed: an unset or empty ``ADMIN_ROLE_NAMES`` denies
everyone, as does a lookup that finds no staff record. An admin console that
opens itself when misconfigured is worse than one nobody can reach.
"""
from __future__ import annotations

from canvas_sdk.v1.data.staff import StaffRole
from logger import log

ADMIN_ROLE_NAMES_SECRET = "ADMIN_ROLE_NAMES"


def admin_role_names(secrets: dict[str, str]) -> set[str]:
    """Return the configured admin role names, casefolded. Empty when unset."""
    raw = (secrets or {}).get(ADMIN_ROLE_NAMES_SECRET, "") or ""
    return {part.strip().casefold() for part in raw.split(",") if part.strip()}


def is_admin_staff(staff_id: str | None, secrets: dict[str, str]) -> bool:
    """Return True if ``staff_id`` holds one of the configured admin roles.

    Matches against both ``StaffRole.name`` (what the instance's admins see,
    e.g. "Practice Manager") and ``StaffRole.internal_code``, so either form
    can be listed in the secret.
    """
    allowed = admin_role_names(secrets)
    if not allowed:
        log.warning(
            f"[authz] {ADMIN_ROLE_NAMES_SECRET} is not configured; "
            "denying access to the appointment-reminders admin"
        )
        return False
    if not staff_id:
        return False

    # One query for the roles rather than fetching the Staff row first.
    held = StaffRole.objects.filter(staff__id=staff_id).values_list(
        "name", "internal_code"
    )
    for name, internal_code in held:
        if (name or "").strip().casefold() in allowed:
            return True
        if (internal_code or "").strip().casefold() in allowed:
            return True

    log.info(f"[authz] Staff {staff_id} holds no configured admin role; denying")
    return False
