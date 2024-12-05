from ai_scribe import parsers
from ai_scribe.parsers.base import ParsedContent
from ai_scribe.parsers.commands.plan import PlanParser

from canvas_sdk.commands.commands.plan import PlanCommand


def test_parse_plan() -> None:
    """Test the `parse` method` of PlanParser."""
    parser = PlanParser()
    command = parsers.ParsedContent(arguments=["Prescribe medication"])
    parsed_commands = parser.parse(command)

    assert len(parsed_commands) == 1
    assert all(isinstance(cmd, PlanCommand) for cmd in parsed_commands)
    assert parsed_commands[0].narrative == "Prescribe medication"


def test_parse_multiple_plans() -> None:
    """Test the `parse` method of PlanParser` with multiple arguments."""
    parser = PlanParser()
    command = ParsedContent(arguments=["Prescribe medication", "Schedule follow-up"])
    parsed_commands = parser.parse(command)

    assert len(parsed_commands) == 2
    assert all(isinstance(cmd, PlanCommand) for cmd in parsed_commands)
    assert parsed_commands[0].narrative == "Prescribe medication"
    assert parsed_commands[1].narrative == "Schedule follow-up"
