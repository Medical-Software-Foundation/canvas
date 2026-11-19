"""Who may use the Practitioner Bulk Loader.

The loader creates staff records and assigns their roles through the plugin's own
FHIR credentials, so it is limited to the staff listed in the plugin variables below.
Staff are matched by staff key, or by any of their roles (internal code, abbreviation
or name). With both variables empty nobody can use it, so a fresh install stays closed
until a practice admin names who may load staff.
"""

from canvas_sdk.v1.data.staff import StaffRole

ALLOWED_STAFF_KEYS_VARIABLE = "BULK_LOADER_ALLOWED_STAFF_KEYS"
ALLOWED_ROLES_VARIABLE = "BULK_LOADER_ALLOWED_ROLES"


def _parse_csv(value: str | None) -> set[str]:
    """Split a comma-separated variable into a set of trimmed, non-empty tokens."""
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def _canonical_key(key: str) -> str:
    """Staff keys are 32 hex characters; accept them with dashes or in any case."""
    return key.replace("-", "").strip().lower()


def _role_tokens(role: StaffRole) -> set[str]:
    """Identifiers a role may be matched by: internal code, abbreviation, or name."""
    return {
        value.casefold()
        for value in (role.internal_code, role.public_abbreviation, role.name)
        if value
    }


def staff_can_load(staff_key: str | None, secrets: dict[str, str]) -> bool:
    """Return whether the given staff member may use the bulk loader.

    Fails closed: with neither variable set, nobody is allowed.
    """
    allowed_keys = {_canonical_key(k) for k in _parse_csv(secrets.get(ALLOWED_STAFF_KEYS_VARIABLE))}
    allowed_roles = {token.casefold() for token in _parse_csv(secrets.get(ALLOWED_ROLES_VARIABLE))}

    if not staff_key or (not allowed_keys and not allowed_roles):
        return False
    if _canonical_key(staff_key) in allowed_keys:
        return True
    if not allowed_roles:
        return False

    roles = StaffRole.objects.filter(staff__id=staff_key)
    return any(_role_tokens(role) & allowed_roles for role in roles)
