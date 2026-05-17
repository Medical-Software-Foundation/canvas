"""Lightweight validators shared across the plugin's handlers.

Currently exposes a UUID-shape check used as a pre-gate on every route
that accepts a note_uuid / patient_id / questionnaire_id from query
params or request bodies. The pre-gate exists because Canvas's SDK
data models declare these fields as ``UUIDField``, which validates
input *before* the SQL filter runs — a non-UUID string raises
``django.core.exceptions.ValidationError`` and (without this gate)
escapes the handler as an empty-body 500 + ~48 MB traceback
allocation. Canvas's plugin sandbox blocks
``django.core.exceptions``, so we can't catch the ValidationError
directly; we pre-validate via ``uuid.UUID()`` (in the stdlib) and bail
with a benign empty response when it raises.
"""
from __future__ import annotations

import uuid


def looks_like_uuid(value: str) -> bool:
    """Return True when ``value`` parses as a UUID string.

    Used by route handlers to short-circuit garbage input BEFORE it
    reaches the ORM. The ``isinstance`` gate handles the non-string
    case, so ``uuid.UUID`` only sees strings; ``ValueError`` is the
    only exception it raises for malformed input.
    """
    if not isinstance(value, str) or not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False
