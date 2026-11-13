"""Facility round visits: label each visit booked in a round, and block a round once it is full.

The work is in engine/round_limits.py. These handlers run on the same appointment
events as the buffer handlers in appointment_buffer.py and leave buffers to them.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.v1.data.appointment import Appointment
from logger import log

from provider_availability.engine.round_limits import visit_effects


def _load(appointment_id: str) -> Appointment | None:
    return (
        Appointment.objects.filter(id=appointment_id, entered_in_error__isnull=True)
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
        log.info("ROUND: rescheduled appt, %d effects", len(effects))
        return effects


class OnRoundVisitCanceled(BaseProtocol):
    """Unblock a full round when one of its visits is cancelled."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CANCELED)

    def compute(self) -> list[Effect]:
        appt = _load(self.event.target.id)
        return visit_effects(appt, label=False) if appt is not None else []


class OnRoundVisitRestored(BaseProtocol):
    """Recount a round when a cancelled visit in it is restored."""

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_RESTORED)

    def compute(self) -> list[Effect]:
        appt = _load(self.event.target.id)
        return visit_effects(appt) if appt is not None else []
