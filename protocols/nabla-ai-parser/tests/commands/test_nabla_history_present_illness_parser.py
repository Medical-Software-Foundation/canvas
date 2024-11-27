from nabla_ai_parser import parsers
from nabla_ai_parser.parsers.nabla.commands.history_present_illness import (
    NablaHistoryPresentIllnessParser,
)

from canvas_sdk.commands.commands.history_present_illness import (
    HistoryOfPresentIllnessCommand,
)


def test_parse_history_present_illness() -> None:
    """Test the `parse` method` of NablaHistoryPresentIllnessParser."""
    parser = NablaHistoryPresentIllnessParser()
    command = parsers.ParsedContent(arguments=["Headache started 3 days ago", "Pain is throbbing"])
    parsed_commands = parser.parse(command)

    assert len(parsed_commands) == 1
    assert all(isinstance(cmd, HistoryOfPresentIllnessCommand) for cmd in parsed_commands)
    assert parsed_commands[0].narrative == "Headache started 3 days ago\nPain is throbbing"
