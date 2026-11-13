"""Queue entry type, status rules and the store logic shared by both backends.

Lifecycle::

    awaiting_assignment -> waiting_for_provider -> in_progress <-> paused -> complete

Each change is a conditional update: it only applies when the entry is still in
the state the change starts from. Two providers claiming the same entry at once
therefore get one success and one "already claimed", never two owners.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class QueueEntryStatus(str, Enum):
    """Status values for queue entries."""

    AWAITING_ASSIGNMENT = "awaiting_assignment"
    WAITING_FOR_PROVIDER = "waiting_for_provider"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETE = "complete"


class QueueEntryPriority(str, Enum):
    """Priority values for queue entries."""

    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENT = "emergent"


ACTIVE_STATUSES: tuple[str, ...] = (
    QueueEntryStatus.AWAITING_ASSIGNMENT.value,
    QueueEntryStatus.WAITING_FOR_PROVIDER.value,
    QueueEntryStatus.IN_PROGRESS.value,
    QueueEntryStatus.PAUSED.value,
)

# Fields a store keeps for every entry, in a stable order.
ENTRY_FIELDS: tuple[str, ...] = (
    "id",
    "patient_id",
    "reason_for_visit",
    "priority",
    "external_id",
    "practice_location_id",
    "status",
    "assigned_provider_id",
    "assigned_provider_name",
    "note_id",
    "created_at",
    "updated_at",
)


def plain(value: Any) -> Any:
    """Return an enum member's value; leave anything else unchanged."""
    return value.value if isinstance(value, Enum) else value


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


@dataclass
class QueueEntry:
    """A single queue entry, independent of where it is stored."""

    id: str
    patient_id: str
    reason_for_visit: str
    priority: str = QueueEntryPriority.ROUTINE.value
    external_id: str | None = None
    practice_location_id: str | None = None
    status: str = QueueEntryStatus.AWAITING_ASSIGNMENT.value
    assigned_provider_id: str | None = None
    assigned_provider_name: str | None = None
    note_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the entry as a JSON-ready dict."""
        return {k: plain(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueueEntry:
        """Build an entry from a dict, ignoring unknown keys."""
        return cls(**{k: data[k] for k in ENTRY_FIELDS if k in data})


@dataclass(frozen=True)
class Where:
    """The state an entry must be in for a conditional update to apply."""

    status_in: tuple[str, ...] = ()
    unassigned: bool = False
    no_note: bool = False
    note_id: str | None = None
    patient_id: str | None = None

    def matches(self, row: dict[str, Any]) -> bool:
        """Return True if a stored row (as a dict) satisfies every condition."""
        if self.status_in and row.get("status") not in self.status_in:
            return False
        if self.unassigned and row.get("assigned_provider_id"):
            return False
        if self.no_note and row.get("note_id"):
            return False
        if self.note_id is not None and row.get("note_id") != self.note_id:
            return False
        return not (self.patient_id is not None and row.get("patient_id") != self.patient_id)


class QueueStore:
    """Queue operations. Backends implement the five storage primitives."""

    # --- storage primitives (implemented by each backend) ---

    def _insert(self, entry: QueueEntry) -> None:
        raise NotImplementedError

    def _get(self, entry_id: str) -> QueueEntry | None:
        raise NotImplementedError

    def _get_by_external_id(self, external_id: str) -> QueueEntry | None:
        raise NotImplementedError

    def _find(self, where: Where) -> list[QueueEntry]:
        """Return matching entries, oldest first."""
        raise NotImplementedError

    def _update_if(self, entry_id: str | None, where: Where, changes: dict[str, Any]) -> str | None:
        """Apply ``changes`` to one entry that matches ``where``.

        With ``entry_id`` the update is limited to that entry; without it, the
        oldest matching entry is used. Returns the updated entry's id, or None
        when nothing matched.
        """
        raise NotImplementedError

    def _delete_where(self, where: Where) -> int:
        raise NotImplementedError

    # --- queue operations ---

    def create_entry(
        self,
        patient_id: str,
        reason_for_visit: str,
        priority: str = QueueEntryPriority.ROUTINE.value,
        external_id: str | None = None,
        practice_location_id: str | None = None,
    ) -> tuple[QueueEntry, bool]:
        """Create an entry. Returns (entry, created).

        A request that repeats an ``external_id`` returns the existing entry and
        ``created=False``, so a sender's retry never adds a second entry.
        """
        if external_id:
            existing = self._get_by_external_id(external_id)
            if existing:
                return existing, False
        stamp = now_utc().isoformat()
        entry = QueueEntry(
            id=str(uuid4()),
            patient_id=patient_id,
            reason_for_visit=reason_for_visit,
            priority=priority,
            external_id=external_id or None,
            practice_location_id=practice_location_id or None,
            created_at=stamp,
            updated_at=stamp,
        )
        self._insert(entry)
        return entry, True

    def get_entry(self, entry_id: str) -> QueueEntry | None:
        """Return one entry, or None."""
        return self._get(entry_id)

    def list_entries(
        self,
        statuses: tuple[str, ...],
        practice_location_id: str | None = None,
        priority: str | None = None,
    ) -> list[QueueEntry]:
        """Return entries in the given statuses, oldest first, optionally filtered."""
        entries = self._find(Where(status_in=statuses))
        if practice_location_id:
            entries = [e for e in entries if e.practice_location_id == practice_location_id]
        if priority:
            entries = [e for e in entries if e.priority == priority]
        return entries

    def _change(
        self, entry_id: str, where: Where, changes: dict[str, Any], refusal: str
    ) -> tuple[QueueEntry | None, str | None]:
        changes = {**changes, "updated_at": now_utc().isoformat()}
        if self._update_if(entry_id, where, changes):
            return self._get(entry_id), None
        if self._get(entry_id) is None:
            return None, "Entry not found"
        return None, refusal

    def claim_entry(
        self, entry_id: str, provider_id: str, provider_name: str
    ) -> tuple[QueueEntry | None, str | None]:
        """Assign an unassigned entry to a provider. Only one claim can win."""
        entry, error = self._change(
            entry_id,
            Where(status_in=(QueueEntryStatus.AWAITING_ASSIGNMENT.value,), unassigned=True),
            {
                "status": QueueEntryStatus.WAITING_FOR_PROVIDER.value,
                "assigned_provider_id": provider_id,
                "assigned_provider_name": provider_name,
            },
            "Entry already claimed",
        )
        if error == "Entry already claimed":
            current = self._get(entry_id)
            if current and current.assigned_provider_id == provider_id:
                return current, None  # same provider clicked twice: no change
        return entry, error

    def release_entry(self, entry_id: str) -> tuple[QueueEntry | None, str | None]:
        """Put an assigned entry that has not started back in the queue."""
        return self._change(
            entry_id,
            Where(
                status_in=(
                    QueueEntryStatus.AWAITING_ASSIGNMENT.value,
                    QueueEntryStatus.WAITING_FOR_PROVIDER.value,
                )
            ),
            {
                "status": QueueEntryStatus.AWAITING_ASSIGNMENT.value,
                "assigned_provider_id": None,
                "assigned_provider_name": None,
            },
            "Can only unassign a visit that has not started",
        )

    def start_entry(self, entry_id: str, note_id: str) -> tuple[QueueEntry | None, str | None]:
        """Move an assigned entry to in_progress and record the new note's id."""
        return self._change(
            entry_id,
            Where(status_in=(QueueEntryStatus.WAITING_FOR_PROVIDER.value,), no_note=True),
            {"status": QueueEntryStatus.IN_PROGRESS.value, "note_id": note_id},
            "Visit cannot be started from its current status",
        )

    def pause_entry(self, entry_id: str) -> tuple[QueueEntry | None, str | None]:
        """Pause an in-progress visit."""
        return self._change(
            entry_id,
            Where(status_in=(QueueEntryStatus.IN_PROGRESS.value,)),
            {"status": QueueEntryStatus.PAUSED.value},
            "Can only pause an in-progress visit",
        )

    def resume_entry(self, entry_id: str) -> tuple[QueueEntry | None, str | None]:
        """Resume a paused visit."""
        return self._change(
            entry_id,
            Where(status_in=(QueueEntryStatus.PAUSED.value,)),
            {"status": QueueEntryStatus.IN_PROGRESS.value},
            "Can only resume a paused visit",
        )

    def complete_for_note(self, note_id: str, patient_id: str | None) -> QueueEntry | None:
        """Complete the entry whose visit note was just locked.

        Matches the entry that recorded this note at Start Visit. Only if none
        does, and the event names a patient, it falls back to that patient's
        oldest started entry that has no note recorded (entries started before
        note ids were stored).
        """
        open_states = (QueueEntryStatus.IN_PROGRESS.value, QueueEntryStatus.PAUSED.value)
        changes = {"status": QueueEntryStatus.COMPLETE.value, "updated_at": now_utc().isoformat()}
        entry_id = self._update_if(None, Where(status_in=open_states, note_id=note_id), changes)
        if not entry_id and patient_id:
            entry_id = self._update_if(
                None,
                Where(status_in=open_states, no_note=True, patient_id=patient_id),
                {**changes, "note_id": note_id},
            )
        return self._get(entry_id) if entry_id else None

    def clear_active(self) -> int:
        """Delete every entry that is not complete (demo mode only)."""
        return self._delete_where(Where(status_in=ACTIVE_STATUSES))
