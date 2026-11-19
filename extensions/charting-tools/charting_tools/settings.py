"""Plugin settings read from the manifest ``secrets`` array."""

from typing import Any

from canvas_sdk.v1.data.staff import Staff

SCRIBE_ENABLED = "SCRIBE_ENABLED"
TEMPLATE_ADMIN_ROLES = "TEMPLATE_ADMIN_ROLES"
# The in-command panel's frame can't send a session cookie, so its calls carry a
# token signed with this key, and post back to this instance address.
PANEL_TOKEN_SIGNING_KEY = "PANEL_TOKEN_SIGNING_KEY"
CANVAS_INSTANCE_URL = "CANVAS_INSTANCE_URL"

# CommandMetadata key holding the command-specific prompt for the scribe.
SCRIBE_PROMPT_METADATA_KEY = "charting_tools:scribe_prompt"


def scribe_enabled(secrets: dict[str, Any]) -> bool:
    """Return whether scribe prompts are turned on. Anything but a true-ish value is off."""
    return (secrets.get(SCRIBE_ENABLED) or "").strip().lower() in {"true", "1", "yes"}


def _admin_roles(secrets: dict[str, Any]) -> set[str]:
    raw = secrets.get(TEMPLATE_ADMIN_ROLES) or ""
    return {token.strip().casefold() for token in raw.split(",") if token.strip()}


def staff_can_manage_templates(staff_id: str | None, secrets: dict[str, Any]) -> bool:
    """Return whether the staff member holds a role listed in TEMPLATE_ADMIN_ROLES.

    Fails closed: with the setting empty, nobody can create or edit templates.
    A role matches by internal code, public abbreviation, or name, case-insensitively.
    """
    allowed = _admin_roles(secrets)
    if not allowed or not staff_id:
        return False
    staff = Staff.objects.filter(id=staff_id).prefetch_related("roles").first()
    if staff is None:
        return False
    for role in staff.roles.all():
        tokens = {
            (value or "").casefold()
            for value in (role.internal_code, role.public_abbreviation, role.name)
        }
        if tokens & allowed:
            return True
    return False


def panel_signing_key(secrets: dict[str, Any]) -> str:
    """HMAC key for panel tokens. Empty means the panel must not render."""
    return (secrets.get(PANEL_TOKEN_SIGNING_KEY) or "").strip()


def instance_url(secrets: dict[str, Any]) -> str:
    """This instance's web address, without a trailing slash."""
    return (secrets.get(CANVAS_INSTANCE_URL) or "").strip().rstrip("/")
