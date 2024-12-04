from typing import Any, Sequence

from ai_scribe.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.history_present_illness import (
    HistoryOfPresentIllnessCommand,
)


class HistoryPresentIllnessParser(CommandParser):
    """Parses the history of present illness section of a transcript."""

    def parse(
        self, content: ParsedContent, context: Any = None
    ) -> Sequence[HistoryOfPresentIllnessCommand]:
        """Parses the given command and returns a command object or list of command objects."""
        return [HistoryOfPresentIllnessCommand(narrative="\n".join(content["arguments"]))]
