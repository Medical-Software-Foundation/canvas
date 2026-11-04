"""Who may see the co-sign summary page, and how much of it.

Two independent doors:

* **Supervisor** — derived, not configured. Anyone who is an active staff
  member's ``default_supervising_provider`` supervises somebody, so they have
  a team to look at. Stays correct on its own as admin changes pairings.
* **Oversight** — configured, via ``COSIGN_OVERSIGHT_STAFF_IDS``. A quality or
  compliance role that supervises nobody but needs the cross-team picture.

Oversight is read-only by construction: co-signing is gated separately, in
``api/handlers.py``, on ``record.supervisor_id == caller``. Attestation is a
clinical-responsibility act tied to a named supervisor, so an oversight viewer
sees every pending row and can sign none of them. Do not "fix" that 403.

Kept free of any Canvas SDK import so it is unit-testable outside the sandbox;
the one database probe it needs is passed in as a boolean.
"""

from __future__ import annotations

from typing import Any

from supervisor_cosign.helpers.staff_allowlist import staff_allowed

#: Comma-separated staff ids that get the cross-team view. Unset means nobody,
#: per the allowlist convention.
OVERSIGHT_SECRET = "COSIGN_OVERSIGHT_STAFF_IDS"


def viewer_role(secrets: Any, staff_id: Any, supervises_someone: bool) -> dict:
    """What this viewer is allowed to see.

    Returns ``{"staff_id", "supervisor", "oversight", "allowed"}``.

    A blank identity is denied **before** the allowlist is consulted. That is a
    deliberate divergence from ``staff_allowed``, which answers the ``"*"``
    wildcard first and would therefore admit an unidentified caller: every
    query behind this page is scoped *by* the viewer's id, so a blank id under
    a wildcard would produce an unscoped, unattributable view of other
    people's patients.
    """
    identity = str(staff_id or "").strip()
    if not identity:
        return {
            "staff_id": "",
            "supervisor": False,
            "oversight": False,
            "allowed": False,
        }
    oversight = bool(staff_allowed(secrets, OVERSIGHT_SECRET, identity))
    supervisor = bool(supervises_someone)
    return {
        "staff_id": identity,
        "supervisor": supervisor,
        "oversight": oversight,
        "allowed": oversight or supervisor,
    }
