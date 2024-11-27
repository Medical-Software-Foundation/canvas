from nabla_ai_parser import parsers
from nabla_ai_parser.parsers.nabla.commands.reason_for_visit import (
    NablaReasonForVisitParser,
)

from canvas_sdk.commands.commands.reason_for_visit import ReasonForVisitCommand


def test_parse_reason_for_visit() -> None:
    """Test the `parse` method` of NablaReasonForVisitParser."""
    parser = NablaReasonForVisitParser()
    command = parsers.ParsedContent(arguments=["Patient reports headache"])
    parsed_commands = parser.parse(command)

    assert len(parsed_commands) == 1
    assert all(isinstance(cmd, ReasonForVisitCommand) for cmd in parsed_commands)
    assert parsed_commands[0].comment == "Patient reports headache"


def test_parse_multiple_reasons_for_visit() -> None:
    """Test the `parse` method of `NablaReasonForVisitParser` with multiple arguments."""
    parser = NablaReasonForVisitParser()
    command = parsers.ParsedContent(arguments=["Patient reports headache", "Patient feels dizzy"])
    parsed_commands = parser.parse(command)

    assert len(parsed_commands) == 1
    assert all(isinstance(cmd, ReasonForVisitCommand) for cmd in parsed_commands)
    assert parsed_commands[0].comment == "Patient reports headache\nPatient feels dizzy"
