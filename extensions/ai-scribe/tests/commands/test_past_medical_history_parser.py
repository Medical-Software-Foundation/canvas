import pytest
from ai_scribe import parsers
from ai_scribe.parsers import ParsedContent
from ai_scribe.parsers.commands.past_medical_history import (
    PastMedicalHistoryParser,
)

from canvas_sdk.commands.commands.medical_history import MedicalHistoryCommand


@pytest.fixture
def transcript_input() -> parsers.ParsedContent:
    """Return an example input for the PastMedicalHistoryParser."""
    return ParsedContent(
        arguments=["Hypertension", "Diabetes", "Asthma"],
        extra={
            "icd_10_codes": [
                {"code": "I10", "text": "Hypertension"},
                {"code": "E11", "text": "Diabetes"},
            ]
        },
    )


def test_parse_past_medical_history_with_codes(transcript_input: parsers.ParsedContent) -> None:
    """Test the `parse` method of PastMedicalHistoryParser with ICD-10 codes."""
    parser = PastMedicalHistoryParser()
    parsed_commands = parser.parse(transcript_input)

    assert len(parsed_commands) == 2
    assert all(isinstance(cmd, MedicalHistoryCommand) for cmd in parsed_commands)
    assert parsed_commands[0].past_medical_history == "I10"
    assert parsed_commands[1].past_medical_history == "E11"


def test_parse_past_medical_history_without_codes(transcript_input: ParsedContent) -> None:
    """Test the `parse` method of PastMedicalHistoryParser without ICD-10 codes."""
    parser = PastMedicalHistoryParser()
    parsed_commands = parser.parse(
        parsers.ParsedContent(arguments=transcript_input["arguments"]), None
    )

    assert len(parsed_commands) == 0
