from typing import Any, Sequence

from ai_scribe.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.reason_for_visit import ReasonForVisitCommand


class ReasonForVisitParser(CommandParser):
    """Parses the reason for visit section of a transcript."""

    def parse(self, content: ParsedContent, context: Any = None) -> Sequence[ReasonForVisitCommand]:
        """Parses the reason for visit section of a transcript."""
        return [ReasonForVisitCommand(comment="\n".join(content["arguments"]))]
