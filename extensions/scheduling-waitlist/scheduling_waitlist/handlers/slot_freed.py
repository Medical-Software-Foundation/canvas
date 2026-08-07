"""Raise a task when a booked slot frees up.

This is the reason the plugin exists: a cancellation today becomes a call list
in the scheduling team's queue within seconds, ordered by priority and wait
time. Staff keep control; nothing is booked automatically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from canvas_sdk.effects import Effect
from canvas_sdk.effects.task import AddTask, AddTaskComment, TaskStatus
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Appointment
from canvas_sdk.v1.data.task import TaskPriority
from django.db import IntegrityError
from logger import log

from scheduling_waitlist.constants import STATUS_WAITING
from scheduling_waitlist.models import SlotNotification
from scheduling_waitlist.services.config import WaitlistConfig
from scheduling_waitlist.services.event_payload import resolve_appointment_id
from scheduling_waitlist.services.matching import (
    find_entries_for_appointment,
    find_matching_entries,
)
from scheduling_waitlist.services.slot import FreedSlot
from scheduling_waitlist.services.task_composer import compose_body, compose_title
from scheduling_waitlist.services.team_resolver import resolve_team_id
from scheduling_waitlist.services.transitions import TransitionError, apply_transition

TASK_LABEL = "waitlist"


class SlotFreedHandler(BaseHandler):
    """Announces a freed slot to the scheduling team, exactly once."""

    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CANCELED),
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),
    ]

    def compute(self) -> list[Effect]:
        """Re-arm any affected entry, then announce the slot if it is fillable."""
        appointment_id = resolve_appointment_id(self.event)
        if not appointment_id:
            log.warning("scheduling_waitlist: appointment event carried no identifier")
            return []

        appointment = (
            Appointment.objects.filter(id=appointment_id, entered_in_error__isnull=True)
            .select_related("patient", "note_type", "provider", "location")
            .first()
        )
        if appointment is None:
            return []

        # Done first, and regardless of whether the slot itself is worth
        # announcing: a patient whose booking has just been cancelled belongs
        # back on the list either way.
        self._rearm_entries(appointment)

        config = WaitlistConfig.from_secrets(self.secrets)
        now = datetime.now(timezone.utc)
        slot = FreedSlot.from_appointment(
            appointment, source_event=str(getattr(self.event, "type", "") or "")
        )

        if slot.note_type_dbid is None:
            log.info("scheduling_waitlist: freed slot has no service; nothing to match")
            return []
        if slot.has_passed(now=now) or slot.starts_within(
            config.min_lead_time_hours, now=now
        ):
            log.info("scheduling_waitlist: freed slot is too soon to fill; skipping")
            return []

        ledger, claimed = self._claim(slot, now)
        if not claimed:
            log.info("scheduling_waitlist: this slot has already been announced")
            return []

        entries = find_matching_entries(
            slot,
            limit=config.max_matches_per_task,
            enforce_time_windows=config.enforce_time_windows,
            fallback_timezone=config.display_timezone,
        )
        if not entries:
            self._record(ledger, entry_count=0, task_id="")
            return []

        team_id = resolve_team_id(config.scheduling_team)
        if not team_id:
            # Fail closed. A task with no team is a task nobody opens, and
            # picking a fallback would quietly drop the notification.
            log.error(
                "scheduling_waitlist: WAITLIST_SCHEDULING_TEAM is not set or does not "
                "match a team, so no slot-opened task was created"
            )
            self._record(ledger, entry_count=len(entries), task_id="")
            return []

        task_id = str(uuid4())
        self._record(ledger, entry_count=len(entries), task_id=task_id)

        return [
            AddTask(
                id=task_id,
                team_id=team_id,
                title=compose_title(
                    slot, len(entries), timezone_name=config.display_timezone
                ),
                due=slot.start_time,
                status=TaskStatus.OPEN,
                priority=self._priority(slot, config, now),
                labels=[TASK_LABEL],
            ).apply(),
            AddTaskComment(
                task_id=task_id,
                body=compose_body(
                    slot,
                    entries,
                    timezone_name=config.display_timezone,
                    today=now.date(),
                ),
            ).apply(),
        ]

    # -- pieces ----------------------------------------------------------

    @staticmethod
    def _priority(slot: FreedSlot, config: WaitlistConfig, now: datetime) -> Any:
        """Urgent when the slot is close enough that it will go to waste."""
        if slot.starts_within(config.urgent_lead_hours, now=now):
            return TaskPriority.URGENT
        return None

    @staticmethod
    def _rearm_entries(appointment: Any) -> None:
        """Put entries this appointment satisfied back on the waiting list.

        Idempotent by construction: it selects only entries still marked
        scheduled against this appointment, so a repeated event matches nothing.
        """
        for entry in find_entries_for_appointment(getattr(appointment, "dbid", None)):
            try:
                apply_transition(
                    entry,
                    to_status=STATUS_WAITING,
                    reason="the booked appointment was cancelled",
                )
            except TransitionError as exc:
                log.warning(f"scheduling_waitlist: could not re-arm an entry: {exc}")

    @staticmethod
    def _claim(slot: FreedSlot, now: datetime) -> tuple[Any, bool]:
        """Take ownership of announcing this slot.

        Claimed before the match runs, so a duplicate event pays one insert
        rather than a full query and a second task.
        """
        try:
            return SlotNotification.objects.get_or_create(
                slot_fingerprint=slot.fingerprint(),
                defaults={
                    "appointment_id": slot.appointment_dbid,
                    "trigger_event": slot.source_event,
                    "notified_at": now,
                },
            )
        except IntegrityError:
            # Lost a race with a concurrent delivery of the same slot.
            return None, False

    @staticmethod
    def _record(ledger: Any, *, entry_count: int, task_id: str) -> None:
        if ledger is None:
            return
        ledger.entry_count = entry_count
        ledger.task_id = task_id
        ledger.save()
