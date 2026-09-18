"""Reading the signed-in user from a Canvas API request."""

from __future__ import annotations


def signed_in_staff_id(request: object) -> str:
    """The staff id of whoever is viewing, or "" when this is not a staff session.

    Canvas identifies the signed-in user with request headers rather than with
    an attribute on the request object: ``canvas-logged-in-user-id`` and
    ``canvas-logged-in-user-type``. Canvas strips both if a client sends them
    and sets them only when there is a valid session, which is what makes them
    safe to trust here. The type is checked so a patient session can never be
    read as a staff member.

    Reading a ``staff_id`` attribute instead fails silently, which is worth
    knowing because this plugin did it in three places: the attribute does not
    exist, so every comparison against a configured staff list fails and the
    caller either denies everyone or falls through to an allow-all branch.
    """
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    if str(headers.get("canvas-logged-in-user-type") or "").strip().lower() != "staff":
        return ""
    return str(headers.get("canvas-logged-in-user-id") or "").strip()
