"""Close waitlist entries when the patient actually gets booked."""

from __future__ import annotations

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data import Appointment
from logger import log

from scheduling_waitlist.constants import STATUS_SCHEDULED
from scheduling_waitlist.services.banner import banner_effects
from scheduling_waitlist.services.event_payload import resolve_appointment_id
from scheduling_waitlist.services.matching import find_entries_to_flip
from scheduling_waitlist.services.transitions import TransitionError, apply_transition


class AppointmentBookedHandler(BaseHandler):
    """Marks an entry scheduled once its patient has a matching appointment.

    The match is strict: the booking must satisfy what the entry actually asked
    for. A looser rule would quietly close requests the patient still wants,
    whereas a strict one occasionally leaves someone on the list -- which staff
    can clear in a click.
    """

    RESPONDS_TO = [EventType.Name(EventType.APPOINTMENT_CREATED)]  # type: ignore[attr-defined]

    def compute(self) -> list[Effect]:
        """Close the entries this booking satisfies, and refresh the chart banner."""
        appointment_id = resolve_appointment_id(self.event)
        if not appointment_id:
            return []

        appointment = (
            Appointment.objects.filter(id=appointment_id, entered_in_error__isnull=True)
            .select_related("patient", "note_type", "provider", "location")
            .first()
        )
        if appointment is None or getattr(appointment, "patient_id", None) is None:
            return []

        # A rescheduled visit arrives as a fresh appointment that points back at
        # the one it replaced. Treating it as a new booking would close an entry
        # on the strength of a move rather than a genuine slot being taken.
        if getattr(appointment, "appointment_rescheduled_from_id", None):
            return []

        flipped = 0
        now = datetime.now(timezone.utc)
        for entry in find_entries_to_flip(appointment):
            try:
                apply_transition(
                    entry,
                    to_status=STATUS_SCHEDULED,
                    reason=f"booked as appointment {appointment_id}",
                    appointment_dbid=getattr(appointment, "dbid", None),
                    now=now,
                )
                flipped += 1
            except TransitionError as exc:
                log.warning(f"scheduling_waitlist: could not close an entry: {exc}")

        if not flipped:
            return []

        log.info(
            f"scheduling_waitlist: closed {flipped} waitlist "
            f"entr{'y' if flipped == 1 else 'ies'} for appointment {appointment_id}"
        )
        # Only when something changed: the banner is recomputed from what is
        # left, so an event that closed nothing has nothing to say.
        return banner_effects(getattr(appointment, "patient", None))
