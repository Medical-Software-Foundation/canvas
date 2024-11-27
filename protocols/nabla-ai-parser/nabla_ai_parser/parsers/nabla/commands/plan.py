from typing import Any, Sequence

from nabla_ai_parser.parsers.base import CommandParser, ParsedContent

from canvas_sdk.commands.commands.plan import PlanCommand


class NablaPlanParser(CommandParser):
    """Parses the plan section of a Nabla transcript."""

    def parse(self, content: ParsedContent, context: Any = None) -> Sequence[PlanCommand]:
        """Parses the plan section of a Nabla transcript."""
        return [PlanCommand(narrative=line) for line in content["arguments"]]
