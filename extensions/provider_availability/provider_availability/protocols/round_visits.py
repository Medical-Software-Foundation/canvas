"""Facility round visits: label each visit booked in a round, and block a round once it is full.

The work is in engine/round_limits.py. These handlers run on the same appointment
events as the buffer handlers in appointment_buffer.py and leave buffers to them.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from logger import log

from provider_availability.engine.round_limits import (
    recheck_full_effects,
    recount_previous,
    remember_visit,
    visit_effects,
    visit_note,
)
from provider_availability.engine.settings import rounds_drawn
from provider_availability.engine.storage import clear_round_visit, get_round_visit


def _load(appointment_id: str) -> Appointment | None:
    """The visit, including one entered in error, so its round is still recounted.

    The count itself leaves entered-in-error visits out (engine.round_limits._visits_qs).
    """
    return (
        Appointment.objects.filter(id=appointment_id)
        .select_related("provider", "appointment_rescheduled_from__provider")
        .first()
    )


class OnRoundVisitCreated(BaseProtocol):
    """Label a new visit booked in a round, and block the round if it is now full."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        appt = _load(self.event.target.id)
        if appt is None or appt.appointment_rescheduled_from is not None:
            # A replacement for a rescheduled visit is handled by the reschedule handler.
            return []
        effects = visit_effects(appt)
        remember_visit(appt)
        log.info("ROUND: created appt %s, %d effects", appt.id, len(effects))
        return effects


class OnRoundVisitRescheduled(BaseProtocol):
    """Recount the round the visit left and the round it moved to, and label it in its new round."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_RESCHEDULED)

    def compute(self) -> list[Effect]:
        appt = _load(self.event.target.id)
        if appt is None:
            return []
        previous = appt.appointment_rescheduled_from
        if previous is None:
            # The event names the original: find where it moved to.
            replacement = Appointment.objects.filter(
                appointment_rescheduled_from__id=appt.id, entered_in_error__isnull=True
            ).select_related("provider").first()
            previous, appt = appt, replacement
        effects: list[Effect] = []
        counted: set = set()
        if previous is not None:
            effects.extend(visit_effects(previous, label=False, counted=counted))
        if appt is not None:
            effects.extend(visit_effects(appt, counted=counted))
            remember_visit(appt)
        log.info("ROUND: rescheduled appt, %d effects", len(effects))
        return effects


class OnRoundVisitCanceled(BaseProtocol):
    """Unblock a full round when one of its visits is cancelled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        appt = _load(self.event.target.id)
        if appt is None:
            return []
        effects = visit_effects(appt, label=False)
        remember_visit(appt)
        return effects


class OnRoundVisitRestored(BaseProtocol):
    """Recount a round when a cancelled visit in it is restored."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_RESTORED)

    def compute(self) -> list[Effect]:
        appt = _load(self.event.target.id)
        if appt is None:
            return []
        effects = visit_effects(appt)
        remember_visit(appt)
        return effects


class OnRoundVisitUpdated(BaseProtocol):
    """Recount rounds when a visit is edited in place or entered in error.

    Canvas sends this for every edit (check-in, room, labels), and the event doesn't say
    what changed. The round handlers save where they last counted each visit of a
    provider with rounds (round_limits.remember_visit), so an edit that leaves the
    provider, start, and countability alone stops after reading the visit, its
    provider's rules, and its note. With rounds off and removed it stops at once. An edit that moves
    the visit recounts its old occurrence and its new one. A visit with no saved note
    (booked before this version, or older than the cache keeps notes) gets its current
    round recounted and its provider's "Round full" blocks rechecked; a move to another
    provider is then not seen. A canceled visit is left to the cancel handler.

    The note is saved here, before Canvas applies the returned effects, as the plugin
    saves all its state. If Canvas rejected the batch, the note would be ahead of the
    calendar and later edits to that visit would be skipped; the next rule save or
    round refresh for the provider rebuilds its "Round full" blocks either way.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_UPDATED)

    def compute(self) -> list[Effect]:
        if not rounds_drawn():
            return []
        appt = _load(self.event.target.id)
        if appt is None or appt.status == AppointmentProgressStatus.CANCELLED:
            return []
        current = visit_note(appt)
        before = get_round_visit(str(appt.id))
        if current is None and before is None:
            return []
        if current == before:
            return []
        counted: set = set()
        effects: list[Effect] = []
        if before is not None:
            effects.extend(recount_previous(before, counted))
        # No label: staff may have removed it on purpose, and an edit shouldn't add it back.
        effects.extend(visit_effects(appt, label=False, counted=counted))
        if before is None and current is not None:
            effects.extend(recheck_full_effects(current["provider_id"], counted))
        if current is not None:
            remember_visit(appt, current)
        else:
            # Moved to a provider with no round: nothing left to compare later edits to.
            clear_round_visit(str(appt.id))
        if effects:
            log.info("ROUND: updated appt %s, %d effects", appt.id, len(effects))
        return effects
