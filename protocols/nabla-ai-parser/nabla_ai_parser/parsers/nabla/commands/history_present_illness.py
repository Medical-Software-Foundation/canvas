from typing import Any, Sequence

from nabla_ai_parser.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.history_present_illness import (
    HistoryOfPresentIllnessCommand,
)


class NablaHistoryPresentIllnessParser(CommandParser):
    """Parses the history of present illness section of a Nabla transcript."""

    def parse(
        self, content: ParsedContent, context: Any = None
    ) -> Sequence[HistoryOfPresentIllnessCommand]:
        """Parses the given command and returns a command object or list of command objects."""
        return [HistoryOfPresentIllnessCommand(narrative="\n".join(content["arguments"]))]
