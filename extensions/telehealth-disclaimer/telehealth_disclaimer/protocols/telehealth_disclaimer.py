import uuid

from canvas_sdk.commands.commands.custom_command import CustomCommand
from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data.note import Note
from logger import log

# Optional plugin secret. Set it to override the disclaimer wording for your
# organization; leave it unset (or blank) to use DEFAULT_DISCLAIMER_TEXT.
DISCLAIMER_TEXT_SECRET = "TELEHEALTH_DISCLAIMER_TEXT"

DEFAULT_DISCLAIMER_TEXT = (
    "This visit was conducted via telehealth using real-time audio and video "
    "technology. The patient was informed of the nature of telehealth services, "
    "including the risks, benefits, and alternatives. The patient provided verbal "
    "consent to proceed with the telehealth visit. The provider confirmed the "
    "patient's identity and location at the start of the encounter. All clinical "
    "decisions were made using the same standard of care as an in-person visit."
)


class TelehealthDisclaimer(BaseProtocol):
    """Inserts a telehealth disclaimer into the plan section when a telehealth note is created."""

    RESPONDS_TO = EventType.Name(EventType.NOTE_STATE_CHANGE_EVENT_CREATED)

    def compute(self) -> list[Effect]:
        if self.event.context.get("state") != "NEW":
            return []

        note_id = self.event.context.get("note_id")
        if not note_id:
            return []

        try:
            note = Note.objects.select_related("note_type_version").get(id=note_id)
        except Note.DoesNotExist:
            return []

        if not note.note_type_version.is_telehealth:
            return []

        log.info(f"Telehealth note detected ({note_id}), inserting disclaimer")

        disclaimer_text = (self.secrets.get(DISCLAIMER_TEXT_SECRET) or "").strip() or DEFAULT_DISCLAIMER_TEXT
        context = {"disclaimer_text": disclaimer_text}

        command = CustomCommand(
            schema_key="telehealthDisclaimer",
            content=render_to_string("templates/disclaimer.html", context),
            print_content=render_to_string("templates/disclaimer_print.html", context),
        )
        command.note_uuid = str(note.id)
        command.command_uuid = str(uuid.uuid4())

        return [command.originate()]
