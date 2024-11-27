from nabla_ai_parser.parsers.nabla import NablaParser

from canvas_sdk.effects import Effect
from canvas_sdk.events import EventType
from canvas_sdk.protocols import BaseProtocol
from logger import log


class Protocol(BaseProtocol):
    """A Plugin for interpreting Nabla transcripts."""

    RESPONDS_TO = EventType.Name(EventType.CLIPBOARD_COMMAND__POST_ORIGINATE)

    def compute(self) -> list[Effect]:
        """Parse the transcript coming from a Clipboard command and return a list of effects to originate Commands."""
        transcript = self.context["fields"]["text"]
        log.debug(f"Processing received transcript: {transcript}")
        parser = NablaParser()
        parsed_transcript = parser.parse(transcript, self.context)
        note_uuid = self.context["note"]["uuid"]

        effects = []
        # update commands with the current note_uuid
        for commands in parsed_transcript.values():
            for command in commands:
                command.note_uuid = note_uuid
                effects.append(command.originate(line_number=1))

        effects.reverse()

        return effects
