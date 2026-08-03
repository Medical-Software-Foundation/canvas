"""Identify the staff member who initiated a Surescripts request.

Surescripts requests run under a provider's SPI, and that provider is not
always the person who clicked the button — the modal lets non-prescribers
(care managers) pick a provider to request on behalf of. Canvas persists the
provider the request ran under (`MedicationHistoryResponse.staff`) but nothing
records who initiated it, so the log line is the only place the two are tied
together. Keep the `Surescripts request:` prefix — it's what makes these
greppable in `canvas logs`.

The `canvas-logged-in-user-id` header is set by Canvas from the session and
stripped if a client sends it, so it's a trustworthy identity.
"""

def logged_in_user_id(request) -> str:
    """The logged-in staff id from the Canvas-set session header."""
    return request.headers.get("canvas-logged-in-user-id", "") or ""


def staff_label(staff, staff_id: str = "") -> str:
    """Format a staff member for a log line as "First Last (id)".

    `staff_id` is the fallback identifier used when the record couldn't be
    resolved, so an unrecognized session still leaves the id in the log.
    """
    if staff is None:
        return "unknown (%s)" % staff_id if staff_id else "unknown"

    first = getattr(staff, "first_name", "") or ""
    last = getattr(staff, "last_name", "") or ""
    name = ("%s %s" % (first, last)).strip()
    return "%s (%s)" % (name or "unnamed", staff.id)
