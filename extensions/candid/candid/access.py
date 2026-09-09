"""Access control for the Candid Dashboard.

The dashboard lists every claim submitted to Candid, so it is billing-sensitive.
By default the provider-menu item is visible to all staff and any authenticated
staff session can open it. Setting either plugin secret below restricts access to
the listed staff keys and/or roles; leaving both unset preserves the open-to-all
behavior so installing this version never locks anyone out.

Only the dashboard surface consults these helpers. The event-driven claim
automation (submit, sync, payment reporting, nightly cron) runs with no logged-in
user and is intentionally left ungated.
"""

from collections.abc import Mapping

from canvas_sdk.v1.data.staff import Staff

ALLOWED_STAFF_KEYS_SECRET = "CANDID_DASHBOARD_ALLOWED_STAFF_KEYS"
ALLOWED_ROLES_SECRET = "CANDID_DASHBOARD_ALLOWED_ROLES"


def _parse_csv(value: str | None) -> set[str]:
    """Split a comma-separated secret into a set of trimmed, non-empty tokens."""
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def _role_tokens(role: object) -> set[str]:
    """Identifiers a role may be matched by: internal code, abbreviation, or name."""
    return {
        value.casefold()
        for value in (
            getattr(role, "internal_code", "") or "",
            getattr(role, "public_abbreviation", "") or "",
            getattr(role, "name", "") or "",
        )
        if value
    }


def staff_can_access_dashboard(staff_key: str | None, secrets: Mapping[str, str]) -> bool:
    """Return whether the given staff member may access the Candid Dashboard.

    Fails open when neither allowlist is set. Once a staff-key and/or role
    allowlist is configured, access requires a matching key or role and everyone
    else is denied.
    """
    allowed_keys = _parse_csv(secrets.get(ALLOWED_STAFF_KEYS_SECRET))
    allowed_roles = {token.casefold() for token in _parse_csv(secrets.get(ALLOWED_ROLES_SECRET))}

    if not allowed_keys and not allowed_roles:
        return True
    if not staff_key:
        return False
    if staff_key in allowed_keys:
        return True
    if not allowed_roles:
        return False

    staff = Staff.objects.filter(id=staff_key).first()
    if staff is None:
        return False
    return any(_role_tokens(role) & allowed_roles for role in staff.roles.all())
