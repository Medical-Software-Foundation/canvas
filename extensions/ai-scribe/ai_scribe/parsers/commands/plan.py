from typing import Any, Sequence

from ai_scribe.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.plan import PlanCommand


class PlanParser(CommandParser):
    """Parses the plan section of a transcript."""

    def parse(self, content: ParsedContent, context: Any = None) -> Sequence[PlanCommand]:
        """Parses the plan section of a transcript."""
        return [PlanCommand(narrative=line) for line in content["arguments"]]
