"""Shared helpers for resolving the logged-in staff from the session header."""

_HEADER = "canvas-logged-in-user-id"


def canonical_staff_id(headers) -> str | None:
    """Return the logged-in staff id in canonical (dashless) form, or None.

    The `canvas-logged-in-user-id` header may arrive as a UUID with or without
    dashes. Staff.id is stored as ``uuid4().hex`` (32 chars, no dashes), so we
    canonicalize to the dashless form. This keeps the value within the 32-char
    column AND makes ``Staff.objects.get(id=...)`` match the stored key
    regardless of which form the platform sends. Both read sites (the feeds API
    and the config page) must use this so stored ids and lookups never diverge.
    """
    raw = headers.get(_HEADER)
    if not raw:
        return None
    return canonicalize_staff_id(raw)


def canonicalize_staff_id(value: str) -> str:
    """Dashless, stripped, lowercased form for case/format-insensitive UUID comparison.

    Staff.id is stored as ``uuid4().hex`` (always lowercase, no dashes). Every
    path that stores, compares, or looks up a staff id must route through this
    single primitive so a mixed-case or dashed id never diverges from the
    stored key.
    """
    return value.replace("-", "").strip().lower()


def is_admin(staff_id, secrets) -> bool:
    """Return True only if ``staff_id`` is listed in the ADMIN_STAFF_IDS secret.

    Fails closed: an unset, empty, or whitespace-only secret means no one is an
    admin. Both the caller id and each configured id are canonicalized to the
    dashless, lowercased form so dashed/uppercase entries still match Staff.id
    (uuid4().hex).
    """
    if not staff_id:
        return False
    raw = (secrets or {}).get("ADMIN_STAFF_IDS") or ""
    admins = {canonicalize_staff_id(part) for part in raw.split(",") if part.strip()}
    if not admins:
        return False
    return canonicalize_staff_id(staff_id) in admins
