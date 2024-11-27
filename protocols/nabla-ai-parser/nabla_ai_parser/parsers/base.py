from enum import StrEnum
from typing import Any, NotRequired, Protocol, Sequence, TypedDict

from canvas_sdk.commands.base import _BaseCommand as Command

TranscriptParserOutput = dict[str, Sequence[Command]]


class ParsedContent(TypedDict):
    """A dictionary representing parsed content from a Nabla transcript section."""

    arguments: Sequence[Any]
    extra: NotRequired[dict[str, Any]]


class TranscriptParser(Protocol):
    """A protocol for parsing transcripts."""

    def parse(self, transcript: str, context: Any | None = None) -> TranscriptParserOutput:
        """Parses the given transcript and returns a dictionary of sections."""
        pass


class CommandParser(Protocol):
    """A protocol for parsing commands."""

    def parse(self, command: ParsedContent, context: Any = None) -> Sequence[Command]:
        """Parses the given command and returns a command object or list of command objects."""
        pass


class TranscriptParserType(StrEnum):
    """An enum representing the supported types of transcript."""

    NABLA = "nabla"
