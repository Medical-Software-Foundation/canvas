"""Keeps a visit note's template in line with its appointment's note type."""

from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.appointment import Appointment, AppointmentProgressStatus
from canvas_sdk.v1.data.note import NoteMetadata
from logger import log

from charting_tools.insertion import APPLIED_METADATA_KEY, auto_apply
from charting_tools.visit_change import switch_template


def _appointment(appointment_id: str) -> Any:
    appointment = (
        Appointment.objects.select_related("note", "note_type")
        # The note's body isn't read here, and it can be large.
        .defer("note___body", "note___body_content", "note___body_order")
        .filter(id=appointment_id, entered_in_error__isnull=True)
        .first()
    )
    if appointment is None:
        log.warning(f"Appointment {appointment_id} not found")
        return None
    # Schedule events (blocked time) have no note.
    if appointment.note is None or appointment.note_type is None:
        return None
    return appointment


class AppointmentCreatedTemplate(BaseHandler):
    """On APPOINTMENT_CREATED, appends the template assigned to the appointment's note type.

    Booking gives the note Canvas's generic Appointment note type until check-in,
    so the match is on the appointment's own note type. A reschedule creates a new
    appointment on the same note: if its note type has a different template, the
    note's template is swapped (see ``visit_change``); otherwise nothing changes.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_CREATED)

    def compute(self) -> list[Effect]:
        """Apply or swap the template for the appointment's note type."""
        appointment = _appointment(self.event.target.id)
        if appointment is None:
            return []
        note = appointment.note
        identifier = str(appointment.note_type.unique_identifier)
        if NoteMetadata.objects.filter(note_id=note.dbid, key=APPLIED_METADATA_KEY).exists():
            return switch_template(note, identifier, self.secrets)
        return auto_apply(note, identifier, self.secrets, mark_untemplated=True)


class AppointmentUpdatedTemplate(BaseHandler):
    """On APPOINTMENT_UPDATED, swaps the note's template when the visit type changed.

    Only the note's current appointment counts: a reschedule also updates the
    appointment it replaced, which still has the old visit type. Canceled and
    no-showed appointments are left alone.
    """

    RESPONDS_TO = EventType.Name(EventType.APPOINTMENT_UPDATED)

    def compute(self) -> list[Effect]:
        """Swap the template if the appointment's note type now has a different one."""
        appointment = _appointment(self.event.target.id)
        if appointment is None:
            return []
        if appointment.status in (AppointmentProgressStatus.CANCELLED, AppointmentProgressStatus.NOSHOWED):
            return []
        latest = (
            Appointment.objects.filter(note_id=appointment.note.dbid, entered_in_error__isnull=True)
            .order_by("-dbid")
            .values_list("id", flat=True)
            .first()
        )
        if str(latest) != str(appointment.id):
            return []
        return switch_template(appointment.note, str(appointment.note_type.unique_identifier), self.secrets)
