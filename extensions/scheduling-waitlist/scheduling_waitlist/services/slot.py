"""A description of an appointment slot that has just freed up."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from scheduling_waitlist.services.display import (
    UNSPECIFIED,
    location_name,
    note_type_name,
    staff_name,
)


@dataclass(frozen=True)
class FreedSlot:
    """What a cancellation or no-show made available.

    A plain value object: the only thing that touches the database is
    :meth:`from_appointment`, so the fingerprint and the task wording can both
    be exercised without one.
    """

    appointment_dbid: Any
    appointment_id: str
    start_time: datetime | None
    duration_minutes: int
    note_type_dbid: Any
    note_type_label: str
    provider_dbid: Any
    provider_label: str
    location_dbid: Any
    location_label: str
    vacating_patient_dbid: Any
    source_event: str

    @classmethod
    def from_appointment(cls, appointment: Any, *, source_event: str = "") -> FreedSlot:
        """Read a slot off an appointment record."""
        note_type = getattr(appointment, "note_type", None)
        provider = getattr(appointment, "provider", None)
        location = getattr(appointment, "location", None)

        return cls(
            appointment_dbid=getattr(appointment, "dbid", None),
            appointment_id=str(getattr(appointment, "id", "") or ""),
            start_time=getattr(appointment, "start_time", None),
            duration_minutes=getattr(appointment, "duration_minutes", 0) or 0,
            note_type_dbid=getattr(appointment, "note_type_id", None),
            note_type_label=(
                note_type_name(note_type) if note_type is not None else UNSPECIFIED
            ),
            provider_dbid=getattr(appointment, "provider_id", None),
            provider_label=staff_name(provider) if provider is not None else UNSPECIFIED,
            location_dbid=getattr(appointment, "location_id", None),
            location_label=(
                location_name(location) if location is not None else UNSPECIFIED
            ),
            vacating_patient_dbid=getattr(appointment, "patient_id", None),
            source_event=source_event,
        )

    def fingerprint(self) -> str:
        """A stable identity for this slot.

        Built from what cannot change without the slot genuinely being a
        different one: which appointment, when, how long, what type, whose, and
        where.

        The event type is deliberately excluded. A cancellation and a no-show
        recorded against the same booking describe the same freed slot, and
        including the event would let each raise its own task for it.
        """
        start = ""
        if isinstance(self.start_time, datetime):
            start = self.start_time.astimezone(timezone.utc).isoformat()

        parts = "|".join(
            [
                str(self.appointment_dbid),
                start,
                str(self.duration_minutes),
                str(self.note_type_dbid),
                str(self.provider_dbid),
                str(self.location_dbid),
            ]
        )
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()

    def starts_within(self, hours: int, *, now: datetime) -> bool:
        """Whether the slot begins sooner than the given lead time.

        Used to skip slots nobody could realistically fill. A slot with no start
        time is treated as too soon, because an unschedulable slot is not worth
        interrupting anyone about.
        """
        if not isinstance(self.start_time, datetime):
            return True
        delta = self.start_time - now
        return delta.total_seconds() < hours * 3600

    def has_passed(self, *, now: datetime) -> bool:
        """Whether the slot has already started."""
        if not isinstance(self.start_time, datetime):
            return True
        return self.start_time <= now
