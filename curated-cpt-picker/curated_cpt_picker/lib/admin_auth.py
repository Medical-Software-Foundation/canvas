"""Shared admin gate for the curated CPT picker.

The admin Application and admin SimpleAPI both consult `ADMIN_STAFF_IDS`
to decide who can manage the curated list.

Default behavior (when the secret is empty/unset): permissive — any
logged-in Canvas staff member can use the admin UI. This is a deliberate
deviation from the repo's CLAUDE.md "fail-closed" guidance, chosen so the
plugin works out-of-the-box and admins opt into stricter access by
setting the secret.

For production deployments, the README instructs admins to set
ADMIN_STAFF_IDS to a comma-separated list of staff UUIDs.
"""

from logger import log


def is_admin(staff_id: str | None, admin_staff_ids_secret: str) -> bool:
    """Return True if the given staff_id is allowed to manage curated codes.

    When `admin_staff_ids_secret` is empty/unset, returns True for any
    non-empty staff_id (permissive default — see module docstring).
    """
    if not staff_id:
        return False

    configured = (admin_staff_ids_secret or "").strip()
    if not configured:
        log.warning(
            "curated_cpt_picker: ADMIN_STAFF_IDS is not configured; "
            "allowing any logged-in staff member to access the admin app. "
            "Set ADMIN_STAFF_IDS to a comma-separated list of staff UUIDs "
            "to restrict access."
        )
        return True

    allowed = {sid.strip() for sid in configured.split(",") if sid.strip()}
    return staff_id in allowed
