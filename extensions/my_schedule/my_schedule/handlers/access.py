"""Who My Schedule restricts, read from the plugin's settings.

A staff member is restricted when any of their roles is listed in
RESTRICTED_ROLES (default MD, NP, PA) and their staff ID is not listed in
EXEMPT_STAFF_IDS. Restricted staff land on My Schedule, don't see the native
Schedule menu item or the Appointments panel filter, and (with BOOK_ONLY_SELF)
can only pick themselves as the provider when booking.
"""

from canvas_sdk.v1.data.staff import Staff

DEFAULT_RESTRICTED_ROLES = frozenset({"MD", "NP", "PA"})

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def parse_list(raw: str | None) -> set[str]:
    """Split a comma-separated setting into a set of trimmed, non-empty values."""
    return {part.strip() for part in (raw or "").split(",") if part.strip()}


def parse_flag(raw: str | None, default: bool) -> bool:
    """Read a yes/no setting. Blank or unrecognized values fall back to the default."""
    value = (raw or "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


def restricted_roles(secrets: dict) -> set[str]:
    """Role codes that restrict a staff member. Blank means the default MD, NP, PA."""
    codes = {code.upper() for code in parse_list(secrets.get("RESTRICTED_ROLES"))}
    return codes or set(DEFAULT_RESTRICTED_ROLES)


def is_restricted(staff: Staff | None, secrets: dict) -> bool:
    """True when the staff member should get the restricted experience."""
    if staff is None:
        return False
    if str(staff.id) in parse_list(secrets.get("EXEMPT_STAFF_IDS")):
        return False
    codes = restricted_roles(secrets)
    return any(role.internal_code.upper() in codes for role in staff.roles.all())


def staff_by_user_dbid(user_dbid: str | None) -> Staff | None:
    """Look up an active staff member by their Canvas user's database id (event actor)."""
    if not user_dbid:
        return None
    try:
        dbid = int(user_dbid)
    except (TypeError, ValueError):
        return None
    return (
        Staff.objects.filter(user__dbid=dbid, active=True).prefetch_related("roles").first()
    )
