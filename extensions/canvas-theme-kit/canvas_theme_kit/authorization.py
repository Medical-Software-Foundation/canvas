"""Role-gated authorization for the theme editor.

Canvas has two unrelated things called "roles" and picking the wrong one is the
easy mistake here:

- `CareTeamRole` is a per-patient care-team assignment ("who is on *this
  patient's* care team"). It is not an authorization construct, and the role
  list shown in an instance configuration report is usually this one.
- `StaffRole`, reachable as `staff.roles`, is the staff member's actual role on
  the organization. That is what gates this plugin.

Roles are matched on `internal_code`, never on `name`: names are display strings
that an organization can rename or localize, and a renamed role must not quietly
grant or revoke access to every stylesheet in the instance.
"""

from typing import Any, Iterable

from canvas_sdk.v1.data.staff import Staff

EDITOR_ROLES_KEY = "DS_EDITOR_ROLES"
PUBLISHER_ROLES_KEY = "DS_PUBLISHER_ROLES"


def parse_role_codes(raw: Any) -> set[str]:
    """Parse a comma-separated allowlist of `StaffRole.internal_code` values."""
    if not raw:
        return set()
    return {code.strip() for code in str(raw).split(",") if code.strip()}


def staff_role_codes(staff: Staff) -> set[str]:
    """Return the `internal_code` of every role held by this staff member."""
    roles: Iterable[Any] = staff.roles.all()
    return {role.internal_code for role in roles if getattr(role, "internal_code", None)}


def current_staff(headers: Any) -> Staff | None:
    """Resolve the staff member behind a session-authenticated request.

    Canvas puts the acting user's id in `canvas-logged-in-user-id`. A patient
    session also carries that header, so this returns None when the id does not
    resolve to a staff member rather than assuming the caller is staff.
    """
    try:
        user_id = headers["canvas-logged-in-user-id"]
    except (KeyError, TypeError):
        return None

    if not user_id:
        return None

    try:
        return Staff.objects.get(id=user_id)
    except Staff.DoesNotExist:
        return None


def can_edit(staff: Staff | None, secrets: Any) -> bool:
    """Whether this staff member may edit drafts and view previews.

    Deny by default: an unconfigured install authorizes nobody. That is
    deliberate and creates no bootstrap problem, because the allowlists are set
    through Canvas's own plugin configuration page (or `canvas config set`),
    which is already admin-gated and lives outside this plugin.
    """
    if staff is None:
        return False
    allowed = parse_role_codes((secrets or {}).get(EDITOR_ROLES_KEY))
    if not allowed:
        return False
    return bool(allowed & staff_role_codes(staff))


def can_publish(staff: Staff | None, secrets: Any) -> bool:
    """Whether this staff member may publish or roll back.

    Publishing is separated from editing because a draft edit is harmless while
    publishing changes every consuming page in the organization at once.

    When `DS_PUBLISHER_ROLES` is unset, publishing falls back to the editor
    allowlist — never to something wider, and never to "any staff member".
    """
    if staff is None:
        return False
    secrets = secrets or {}
    allowed = parse_role_codes(secrets.get(PUBLISHER_ROLES_KEY))
    if not allowed:
        allowed = parse_role_codes(secrets.get(EDITOR_ROLES_KEY))
    if not allowed:
        return False
    return bool(allowed & staff_role_codes(staff))
