"""Access check for the failed-fax dashboard.

Deliberately open by default: when the ``FAX_DASHBOARD_STAFF_IDS`` secret is
empty or unset, every logged-in staff member may use the dashboard. When it is
set, only the listed staff ids may. This differs from the repo's fail-closed
guidance for admin checks on purpose: the dashboard shows nothing a staff member
cannot already see on each faxed item.
"""

STAFF_IDS_SECRET = "FAX_DASHBOARD_STAFF_IDS"


def allowed_staff_ids(secrets: dict[str, str]) -> set[str]:
    """Return the lowercase staff ids listed in the secret (empty set when unset)."""
    raw = secrets.get(STAFF_IDS_SECRET) or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def is_staff_allowed(secrets: dict[str, str], staff_id: str | None) -> bool:
    """Return True when the staff member may use the dashboard."""
    allowed = allowed_staff_ids(secrets)
    if not allowed:
        return True
    if not staff_id:
        return False
    return staff_id.strip().lower() in allowed
