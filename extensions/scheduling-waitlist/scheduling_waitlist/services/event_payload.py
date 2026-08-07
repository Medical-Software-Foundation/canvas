"""Reading an appointment identifier off an event, defensively."""

from __future__ import annotations

from typing import Any


def resolve_appointment_id(event: Any) -> str | None:
    """Best-effort extraction of an appointment identifier from an event.

    Appointment events carry the identifier on ``target`` and ship an empty
    context, so that is checked first. The context is probed afterwards only as
    a fallback, since nothing guarantees its shape.

    Every access is a type check rather than a ``try``: partial payloads are
    normal in production, and a handler that raises on one takes the whole
    event with it.
    """
    target = getattr(event, "target", None)
    target_id = getattr(target, "id", None)
    if isinstance(target_id, str) and target_id:
        return target_id

    context = getattr(event, "context", None)
    if not isinstance(context, dict):
        return None

    appointment = context.get("appointment")
    if isinstance(appointment, dict):
        candidate = appointment.get("id")
        if isinstance(candidate, str) and candidate:
            return candidate

    candidate = context.get("appointment_id")
    if isinstance(candidate, str) and candidate:
        return candidate

    return None
