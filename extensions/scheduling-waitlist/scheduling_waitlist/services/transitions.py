"""Which status changes are allowed, and how they are recorded.

Kept in one place so the API, the appointment handlers, and the nightly job
cannot drift apart about what a status means.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scheduling_waitlist.constants import (
    ALL_STATUSES,
    AUTOMATED_STATUSES,
    MAX_REASON_LENGTH,
    STATUS_EXPIRED,
    STATUS_OFFERED,
    STATUS_REMOVED,
    STATUS_SCHEDULED,
    STATUS_WAITING,
)

# Every terminal status can be reinstated: a patient who calls back after being
# removed, expired, or booked should not have to be re-keyed from scratch.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_WAITING: frozenset({STATUS_OFFERED, STATUS_SCHEDULED, STATUS_REMOVED, STATUS_EXPIRED}),
    STATUS_OFFERED: frozenset({STATUS_WAITING, STATUS_SCHEDULED, STATUS_REMOVED, STATUS_EXPIRED}),
    STATUS_SCHEDULED: frozenset({STATUS_WAITING, STATUS_REMOVED}),
    STATUS_REMOVED: frozenset({STATUS_WAITING}),
    STATUS_EXPIRED: frozenset({STATUS_WAITING, STATUS_REMOVED}),
}


class TransitionError(Exception):
    """The requested status change is not allowed."""


def is_allowed(from_status: str, to_status: str) -> bool:
    """Whether a status may move from one value to another."""
    if to_status not in ALL_STATUSES:
        return False
    if from_status == to_status:
        return False
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def requires_reason(from_status: str) -> bool:
    """Whether leaving this status needs an explanation.

    Something automated put the entry into a scheduled or expired state, so a
    person overriding that should say why. The record is otherwise misleading.
    """
    return from_status in AUTOMATED_STATUSES


def validate_transition(from_status: str, to_status: str, reason: str) -> str:
    """Check a status change and return the reason to store.

    Raises :class:`TransitionError` with a message meant for a person.
    """
    if to_status not in ALL_STATUSES:
        raise TransitionError("That is not a status an entry can have.")
    if from_status == to_status:
        raise TransitionError(f"This entry is already {to_status}.")
    if not is_allowed(from_status, to_status):
        raise TransitionError(f"An entry cannot move from {from_status} to {to_status}.")
    if requires_reason(from_status) and not reason.strip():
        raise TransitionError("Give a reason for changing an automatic status.")
    return reason.strip()[:MAX_REASON_LENGTH]


def apply_transition(
    entry: Any,
    *,
    to_status: str,
    reason: str = "",
    actor_dbid: Any = None,
    appointment_dbid: Any = None,
    now: datetime | None = None,
) -> Any:
    """Move an entry to a new status and record who did it and why.

    Validates first, so a refused change never half-writes.
    """
    from_status = getattr(entry, "status", "") or ""
    stored_reason = validate_transition(from_status, to_status, reason)

    entry.status = to_status
    entry.status_reason = stored_reason
    entry.status_changed_at = now or datetime.now(timezone.utc)
    entry.status_changed_by_id = actor_dbid

    if to_status == STATUS_SCHEDULED:
        entry.scheduled_appointment_id = appointment_dbid
    elif from_status == STATUS_SCHEDULED:
        # Leaving "scheduled" means that booking no longer stands, so the link
        # has to go with it or the entry keeps pointing at a dead appointment.
        entry.scheduled_appointment_id = None

    entry.save()
    return entry
