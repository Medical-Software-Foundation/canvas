"""Default a note's supervising provider from the provider's Staff record.

Canvas intentionally does not auto-populate ``Note.supervising_provider`` from
``Staff.default_supervising_provider`` — that defaulting is left to customers so
they stay in control. This reference plugin demonstrates the pattern: when a note
is created, if the note's provider has a ``default_supervising_provider`` configured
on their Staff record, copy it onto the note's supervising provider.

Adapt the ``compute`` logic to fit your workflow — for example, only default for
certain note types or providers, or always overwrite an existing value.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.note import Note as NoteEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.v1.data import Note

from logger import log


class DefaultSupervisingProvider(BaseHandler):
    """Default the supervising provider on note creation from the rendering provider."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_CREATED)

    def compute(self) -> list[Effect]:
        note = Note.objects.get(id=self.event.target.id)

        provider = note.provider
        if provider is None:
            return []

        default_supervising = provider.default_supervising_provider
        if default_supervising is None:
            return []

        # Don't override a supervising provider that's already set on the note.
        if note.supervising_provider_id:
            return []

        log.info(
            f"Defaulting supervising provider {default_supervising.id} "
            f"on note {note.id} from provider {provider.id}"
        )
        return [
            NoteEffect(
                instance_id=str(note.id),
                supervising_provider_id=str(default_supervising.id),
            ).update()
        ]
