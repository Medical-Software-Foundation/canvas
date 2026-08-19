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
from scheduling_waitlist.services.banner import banner_effects
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

    # Every channel a booked slot can open through. Subscribing only to the
    # staff-side cancellation misses the portal, which is where most patients
    # cancel, and misses reschedules, which free the original slot silently.
    # Duplicate deliveries are harmless: the slot fingerprint collapses them.
    RESPONDS_TO = [
        EventType.Name(EventType.APPOINTMENT_CANCELED),  # type: ignore[attr-defined]
        EventType.Name(EventType.APPOINTMENT_NO_SHOWED),  # type: ignore[attr-defined]
        EventType.Name(EventType.APPOINTMENT_RESCHEDULED),  # type: ignore[attr-defined]
        EventType.Name(EventType.PATIENT_PORTAL__APPOINTMENT_CANCELED),  # type: ignore[attr-defined]
        EventType.Name(EventType.PATIENT_PORTAL__APPOINTMENT_RESCHEDULED),  # type: ignore[attr-defined]
    ]

    RELATED = ("patient", "note_type", "provider", "location")

    def compute(self) -> list[Effect]:
        """Re-arm any affected entry, then announce the slot if it is fillable."""
        appointment_id = resolve_appointment_id(self.event)
        if not appointment_id:
            log.warning("scheduling_waitlist: appointment event carried no identifier")
            return []

        appointment = (
            Appointment.objects.filter(id=appointment_id, entered_in_error__isnull=True)
            .select_related(*self.RELATED)
            .first()
        )
        if appointment is None:
            return []

        # Done first, and regardless of whether the slot itself is worth
        # announcing: a patient whose booking has just been cancelled belongs
        # back on the list either way. Its banner refresh rides along on every
        # return below, including the ones that decline to announce the slot.
        banner = self._rearm_entries(appointment)

        config = WaitlistConfig.from_secrets(self.secrets)
        now = datetime.now(timezone.utc)
        slot = FreedSlot.from_appointment(
            self._freed_appointment(appointment),
            # The event's *name*, not its type. ``event.type`` is the protobuf
            # enum integer, so this used to put "Slot freed (4)" in front of
            # schedulers. The fingerprint deliberately excludes the event, so
            # changing this does not disturb the duplicate-task guard.
            source_event=str(getattr(self.event, "name", "") or ""),
        )

        if slot.note_type_dbid is None:
            log.info("scheduling_waitlist: freed slot has no service; nothing to match")
            return banner
        if slot.has_passed(now=now) or slot.starts_within(
            config.min_lead_time_hours, now=now
        ):
            log.info("scheduling_waitlist: freed slot is too soon to fill; skipping")
            return banner

        # Checked before the slot is claimed, so a misconfigured team costs
        # nothing. Claiming first meant an instance with no usable team burned
        # every slot's fingerprint on the way past, leaving them unannounceable
        # even once the configuration was corrected.
        team_id = resolve_team_id(config.scheduling_team)
        if not team_id:
            # Fail closed. A task with no team is a task nobody opens, and
            # picking a fallback would quietly drop the notification.
            log.error(
                "scheduling_waitlist: WAITLIST_SCHEDULING_TEAM is not set or does not "
                "match a team, so no slot-opened task was created"
            )
            return banner

        ledger, claimed = self._claim(slot, now)
        if not claimed:
            log.info("scheduling_waitlist: this slot has already been announced")
            return banner

        entries = find_matching_entries(
            slot,
            limit=config.max_matches_per_task,
            enforce_time_windows=config.enforce_time_windows,
            fallback_timezone=config.display_timezone,
        )
        if not entries:
            # Said out loud. This is the commonest answer to "why was there no
            # task", and staying silent meant it could only be inferred from the
            # absence of the other log lines.
            log.info(
                "scheduling_waitlist: freed slot matched nobody on the waitlist; "
                "no task raised"
            )
            self._record(ledger, entry_count=0, task_id="")
            return banner

        task_id = str(uuid4())
        self._record(ledger, entry_count=len(entries), task_id=task_id)
        log.info(
            f"scheduling_waitlist: freed slot matched {len(entries)} "
            f"waitlisted patient{'' if len(entries) == 1 else 's'}; raising one task"
        )

        return [
            *banner,
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
                    enforce_time_windows=config.enforce_time_windows,
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

    @classmethod
    def _freed_appointment(cls, appointment: Any) -> Any:
        """The appointment whose slot actually opened.

        A reschedule event names the new booking, so announcing that would
        advertise a slot somebody already holds. The slot that opened is the one
        it moved away from, reached through ``appointment_rescheduled_from_id``.

        Falls back to the event's own appointment when the original cannot be
        loaded -- announcing the wrong start time is a smaller failure than
        going silent, and the guards downstream still apply.
        """
        origin_dbid = getattr(appointment, "appointment_rescheduled_from_id", None)
        if not origin_dbid:
            return appointment

        origin = (
            Appointment.objects.filter(dbid=origin_dbid, entered_in_error__isnull=True)
            .select_related(*cls.RELATED)
            .first()
        )
        if origin is None:
            log.warning(
                "scheduling_waitlist: could not load the appointment this booking was "
                "rescheduled from; announcing the event's own appointment instead"
            )
            return appointment
        return origin

    @staticmethod
    def _rearm_entries(appointment: Any) -> list[Effect]:
        """Put entries this appointment satisfied back on the waiting list.

        Idempotent by construction: it selects only entries still marked
        scheduled against this appointment, so a repeated event matches nothing.

        Skipped when the booking was moved rather than cancelled: the patient
        still has an appointment, so putting them back on the list would claim
        they are waiting when they are booked. Deliberately keyed on the event's
        own appointment rather than the freed one, so a reschedule cannot re-arm
        the entry it just satisfied.

        Returns the banner refresh for the affected patient, so their chart stops
        claiming they are booked. Empty when nothing was re-armed.
        """
        moved_elsewhere = getattr(appointment, "appointment_rescheduled_to", None)
        if moved_elsewhere is not None and moved_elsewhere.exists():
            return []

        rearmed = False
        for entry in find_entries_for_appointment(getattr(appointment, "dbid", None)):
            try:
                apply_transition(
                    entry,
                    to_status=STATUS_WAITING,
                    reason="the booked appointment was cancelled",
                )
                rearmed = True
            except TransitionError as exc:
                log.warning(f"scheduling_waitlist: could not re-arm an entry: {exc}")

        if not rearmed:
            return []
        return banner_effects(getattr(appointment, "patient", None))

    @staticmethod
    def _claim(slot: FreedSlot, now: datetime) -> tuple[Any, bool]:
        """Take ownership of announcing this slot.

        Claimed before the match runs, so a duplicate event pays one insert
        rather than a full query and a second task.

        Claimed *after* the team is resolved, though: the fingerprint is spent
        once written, so it must only be spent on a slot this instance is
        actually able to announce.

        A row that raised no task does not block a later attempt. The guard
        exists because one cancellation can reach the plugin several times within
        seconds, and each delivery would otherwise raise its own task. It is not
        meant to mean "this slot may never be announced": a slot freed while
        nobody was waiting, then freed again after someone joined the list,
        deserves its task. Only a row carrying a real task id closes the door.
        """
        try:
            ledger, created = SlotNotification.objects.get_or_create(
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

        if created:
            return ledger, True

        if str(getattr(ledger, "task_id", "") or "").strip():
            return ledger, False

        # Re-announcing: record this freeing as the one that counts.
        ledger.trigger_event = slot.source_event
        ledger.notified_at = now
        return ledger, True

    @staticmethod
    def _record(ledger: Any, *, entry_count: int, task_id: str) -> None:
        """Store the outcome of this announcement.

        A full ``save()`` rather than an update of two columns, so the
        ``trigger_event`` and ``notified_at`` that ``_claim`` refreshed on a
        re-announcement are persisted with it.
        """
        if ledger is None:
            return
        ledger.entry_count = entry_count
        ledger.task_id = task_id
        ledger.save()
