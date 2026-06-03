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
    return raw.replace("-", "")
