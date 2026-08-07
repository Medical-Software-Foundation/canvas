"""Who is acting, and what they are allowed to do to an entry.

The session mixin on the API classes answers "is this a signed-in staff
member". It does not answer "may this person delete a colleague's entry", which
is what this module is for.
"""

from __future__ import annotations

import uuid
from typing import Any

from canvas_sdk.v1.data import Staff


def staff_id_candidates(raw: str) -> set[str]:
    """Every form of an identifier that should match the stored staff key.

    ``Staff.id`` is a 32-character key column, while the
    ``canvas-logged-in-user-id`` header may arrive dashed or undashed depending
    on the session. Comparing the raw header against the column therefore
    misses half the time.

    The obvious ``{value, value.replace("-", "")}`` only produces both forms
    when the input happens to be dashed; an undashed input yields a single
    entry that never matches a dashed record. Parsing through ``uuid.UUID``
    adds the canonical dashed form whichever way the header arrived.
    """
    value = (raw or "").strip()
    if not value:
        return set()
    candidates = {value, value.replace("-", "")}
    try:
        candidates.add(str(uuid.UUID(value)))
    except ValueError:
        # Not UUID-shaped. The literal forms above are still worth trying.
        pass
    return candidates


def staff_from_session(user_id: str | None) -> Any | None:
    """Resolve the acting staff member from the session header.

    Returns ``None`` when the header is absent or matches nobody. Callers must
    refuse the request in that case rather than substituting a placeholder:
    a waitlist entry attributed to "unknown" is worse than no entry at all.
    """
    candidates = staff_id_candidates(user_id or "")
    if not candidates:
        return None
    return Staff.objects.filter(id__in=candidates).first()


def can_manage_all(staff: Any | None, manager_role_codes: tuple[str, ...]) -> bool:
    """Whether this person may modify entries other people created.

    Fails closed. With no manager roles configured nobody gains that power,
    which is not a lockout: everyone still manages what they created. Granting
    it by default would mean a blank configuration silently handing every staff
    member the ability to clear the roster.
    """
    if staff is None or not manager_role_codes:
        return False

    allowed = {code.upper() for code in manager_role_codes}

    top_role = getattr(staff, "top_clinical_role", None)
    top_code = (getattr(top_role, "internal_code", "") or "").upper()
    if top_code and top_code in allowed:
        return True

    roles = getattr(staff, "roles", None)
    if roles is None:
        return False
    try:
        role_list = list(roles.all())
    except (AttributeError, TypeError):
        return False

    return any(
        (getattr(role, "internal_code", "") or "").upper() in allowed for role in role_list
    )


def can_modify_entry(entry: Any, staff: Any | None, manages_all: bool) -> bool:
    """Whether this person may edit, re-status, or remove a given entry."""
    if staff is None:
        return False
    if manages_all:
        return True
    creator_dbid = getattr(entry, "created_by_id", None)
    return creator_dbid is not None and creator_dbid == getattr(staff, "dbid", None)
