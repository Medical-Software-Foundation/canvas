DEFAULT_ADMIN_ROLE_CODES = ("ADMIN", "OWNER")


def parse_admin_role_codes(raw: str | None) -> tuple[str, ...]:
    """Parse the ADMIN_ROLE_CODES secret value into a tuple of uppercase codes."""
    if not raw:
        return DEFAULT_ADMIN_ROLE_CODES
    codes = tuple(c.strip().upper() for c in raw.split(",") if c.strip())
    return codes or DEFAULT_ADMIN_ROLE_CODES


def is_admin(staff, admin_role_codes: tuple[str, ...]) -> bool:
    """Return True if the given Staff instance has any of the admin role codes.

    Staff roles in Canvas expose an `internal_code` (e.g. "MD", "ADMIN"). We check the
    primary/top clinical role first, then fall back to any role on the record.
    """
    if staff is None:
        return False

    codes_upper = tuple(c.upper() for c in admin_role_codes)

    top_role = getattr(staff, "top_clinical_role", None)
    if top_role is not None:
        code = getattr(top_role, "internal_code", "") or ""
        if code.upper() in codes_upper:
            return True

    roles_manager = getattr(staff, "roles", None)
    if roles_manager is not None:
        try:
            for role in roles_manager.all():
                code = getattr(role, "internal_code", "") or ""
                if code.upper() in codes_upper:
                    return True
        except Exception:
            return False
    return False
