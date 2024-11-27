from typing import Any, Sequence

from nabla_ai_parser.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.reason_for_visit import ReasonForVisitCommand


class NablaReasonForVisitParser(CommandParser):
    """Parses the reason for visit section of a Nabla transcript."""

    def parse(self, content: ParsedContent, context: Any = None) -> Sequence[ReasonForVisitCommand]:
        """Parses the reason for visit section of a Nabla transcript."""
        return [ReasonForVisitCommand(comment="\n".join(content["arguments"]))]
