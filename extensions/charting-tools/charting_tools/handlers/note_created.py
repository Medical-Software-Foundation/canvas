"""Inserts a template's commands into notes created directly with an assigned note type."""

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import Note
from logger import log

from charting_tools.insertion import auto_apply
from charting_tools.note_types import note_type_identifier


class NoteCreatedTemplate(BaseHandler):
    """On NOTE_CREATED, appends the template assigned to the note's type.

    A note created by booking an appointment has Canvas's generic Appointment
    note type at this point, so it never matches here; AppointmentCreatedTemplate
    covers those. Canvas sends NOTE_CREATED once the note commits and refreshes
    the note afterward, so the commands are in place when it opens.
    """

    RESPONDS_TO = EventType.Name(EventType.NOTE_CREATED)

    def compute(self) -> list[Effect]:
        """Apply the matching template, if any, to the new note."""
        note = (
            Note.objects.select_related("note_type_version")
            .defer("body")
            .filter(id=self.event.target.id)
            .first()
        )
        if note is None:
            log.warning(f"Created note {self.event.target.id} not found")
            return []

        identifier = note_type_identifier(note)
        if not identifier:
            return []
        return auto_apply(note, identifier, self.secrets)
