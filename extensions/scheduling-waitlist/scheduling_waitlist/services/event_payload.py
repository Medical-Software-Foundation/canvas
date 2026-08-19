"""Reading an appointment identifier off an event, defensively."""

from __future__ import annotations

from typing import Any


def resolve_note_state_change_id(event: Any) -> str | None:
    """Best-effort extraction of the identifier a note-state-change event carries.

    Kept pure, like :func:`resolve_appointment_id`: what the identifier *points at*
    is a question for the caller, because the platform may name either the
    state-change row or the note itself and only a lookup can tell them apart.

    Every access is a type check rather than a ``try``, for the same reason as
    below: a partial payload is normal, and a handler that raises on one takes the
    whole event with it.
    """
    target = getattr(event, "target", None)
    target_id = getattr(target, "id", None)
    if isinstance(target_id, str) and target_id:
        return target_id

    context = getattr(event, "context", None)
    if not isinstance(context, dict):
        return None

    for key in ("note_state_change_event_id", "note_id", "id"):
        candidate = context.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate

    note = context.get("note")
    if isinstance(note, dict):
        candidate = note.get("id")
        if isinstance(candidate, str) and candidate:
            return candidate

    return None


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
