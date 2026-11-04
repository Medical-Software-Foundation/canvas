"""Resolving the signed-in user from the session headers.

Canvas strips ``canvas-logged-in-user-id`` and ``canvas-logged-in-user-type`` if
a client sends them, and sets them only when there is a live session. That makes
them the one trustworthy identity in a request -- and the only one this plugin
uses. Nothing is ever read from a request body or query parameter.
"""

import uuid
from typing import Any

from canvas_sdk.v1.data import Patient, Staff

from patient_resources.constants import SESSION_ID_HEADER


def id_candidates(raw: str) -> set[str]:
    """Every form of an id that could match a 32-character key column.

    Both ``Patient.id`` and ``Staff.id`` are ``CharField(max_length=32,
    db_column="key")`` -- not UUID fields, despite how they look. The session
    header may arrive dashed or undashed, and an exact filter on the wrong form
    matches nothing and raises nothing: the lookup just silently comes back
    empty.

    ``{value, value.replace("-", "")}`` is not enough on its own. That covers a
    dashed input, but an undashed input yields only the one form it came in as
    and would never match a dashed record. Parsing through ``uuid.UUID`` adds the
    canonical dashed form whichever way the header arrived.

    Note that the safety here depends on the column being a CharField. Against a
    real UUIDField a malformed value would raise rather than miss, which is a 500
    instead of a silent empty result.
    """
    value = (raw or "").strip()
    if not value:
        return set()

    candidates = {value, value.replace("-", "")}
    try:
        candidates.add(str(uuid.UUID(value)))
    except (ValueError, AttributeError, TypeError):
        # Not a UUID at all. The literal is still worth trying: nothing
        # guarantees these keys are UUID-shaped.
        pass
    return {candidate for candidate in candidates if candidate}


def _resolve(manager: Any, raw: str) -> Any | None:
    candidates = id_candidates(raw)
    if not candidates:
        return None
    return manager.filter(id__in=list(candidates)).only("id", "dbid").first()


def staff_from_session(request: Any) -> Any | None:
    """The ``Staff`` row behind a staff session, or ``None``.

    ``None`` must become a 401. It must never become a placeholder: a resource
    attributed to "unknown" is worse than no resource at all, because it looks
    like a real audit trail and is not one.
    """
    return _resolve(Staff.objects, _header(request))


def patient_from_session(request: Any) -> Any | None:
    """The ``Patient`` row behind a portal session, or ``None``.

    Resolved against ``Patient``, not ``Staff``. The header name is identical on
    both surfaces -- ``canvas-logged-in-user-type`` is the discriminator -- so a
    helper pointed at the wrong model returns ``None`` for every caller and 401s
    every patient.
    """
    return _resolve(Patient.objects, _header(request))


def _header(request: Any) -> str:
    """Read the session id from the request headers.

    Always ``request.headers``, which is a case-insensitive multidict, rather
    than ``event.context["headers"]``, which is a plain case-sensitive mapping
    and forces callers to try both spellings.
    """
    headers = getattr(request, "headers", None) or {}
    return str(headers.get(SESSION_ID_HEADER, "") or "")
