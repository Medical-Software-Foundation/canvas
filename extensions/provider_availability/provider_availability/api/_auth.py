"""Shared access-control helpers for the provider-availability plugin APIs.

The admin UI and write endpoints both gate on the `allowed-staff-keys` plugin
secret. Empty/unset secret means any logged-in Canvas staff member is allowed
(``StaffSessionAuthMixin`` enforces the logged-in baseline). A configured
secret restricts access to the listed staff UUIDs.
"""

from __future__ import annotations

from uuid import UUID


def _canonical_id(value: str) -> str:
    """Return ``value`` in canonical UUID hex form, or verbatim if not a UUID.

    Canvas exposes ``Staff.id`` as ``uuid.uuid4().hex`` (32-char undashed), but
    operators routinely paste dashed UUIDs into plugin secrets. Canonicalising
    both sides through ``UUID(...)`` lets dashed and undashed forms compare
    equal. Non-UUID strings (legacy test fixtures) pass through unchanged.
    """
    s = (value or "").strip()
    if not s:
        return ""
    try:
        return UUID(s).hex
    except (ValueError, AttributeError):
        return s


def current_staff_id(request: object) -> str:
    """Return the canonicalised staff id of the caller, or ``""`` if absent.

    Reads ``canvas-logged-in-user-id`` from the request headers — this is the
    only source ``StaffSessionAuthMixin`` populates. ``request.staff_id`` does
    not exist on the SDK ``Request`` and earlier code that read it was
    silently returning ``None``.
    """
    headers = getattr(request, "headers", {}) or {}
    raw = headers.get("canvas-logged-in-user-id") or headers.get(
        "Canvas-Logged-In-User-Id"
    ) or ""
    return _canonical_id(str(raw))


def is_authorized(secrets: dict | None, request: object) -> bool:
    """True iff the caller is allowed to use the admin UI / write endpoints.

    Empty/unset ``allowed-staff-keys`` → allow any logged-in staff (bootstrap).
    Configured secret → the caller's canonicalised staff id must appear in the
    canonicalised allowlist.
    """
    raw = ((secrets or {}).get("allowed-staff-keys", "") or "")
    allowed = {_canonical_id(part) for part in raw.split(",") if part.strip()}
    if not allowed:
        return True
    staff_id = current_staff_id(request)
    return bool(staff_id) and staff_id in allowed
