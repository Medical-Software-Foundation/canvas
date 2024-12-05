import pytest
from ai_scribe.parsers.parser import ScribeParser

from canvas_sdk.commands.base import _BaseCommand


@pytest.fixture
def sample_transcript() -> str:
    """Fixture that provides a sample transcript for testing."""
    return """
    Chief Complaint
    - Patient reports headache

    History of Present Illness
    - Headache started 3 days ago
    - Pain is throbbing

    Past Medical History
    - Hypertension
    - Diabetes

    Vitals
    - Blood Pressure: 120/80
    - Heart Rate: 72

    Plan
    - Prescribe medication

    ICD-10 Codes
    - Headache [R51]
    - Hypertension [I10]
    """


def test_parse_sections(sample_transcript: str) -> None:
    """Test the `parse_sections` method of `ScribeParser`."""
    parser = ScribeParser()
    sections = parser.parse_sections(sample_transcript)

    assert "chief_complaint" in sections
    assert "history_of_present_illness" in sections
    assert "past_medical_history" in sections
    assert "vitals" in sections
    assert "plan" in sections
    assert "icd_10_codes" not in sections  # ICD-10 codes should be merged into other sections


def test_parse_icd10_section() -> None:
    """Test the `parse_icd10_section` method of `ScribeParser`."""
    parser = ScribeParser()
    icd10_lines = ["- Headache [R51]", "- Hypertension [I10]"]
    icd10_list = parser.parse_icd10_section(icd10_lines)

    assert len(icd10_list) == 2
    assert icd10_list[0] == {"code": "R51", "text": "Headache"}
    assert icd10_list[1] == {"code": "I10", "text": "Hypertension"}


def test_parse(sample_transcript: str) -> None:
    """Test the `parse` method of `ScribeParser`."""
    parser = ScribeParser()
    parsed_data = parser.parse(sample_transcript)

    assert "chief_complaint" in parsed_data
    assert "history_of_present_illness" in parsed_data
    assert "past_medical_history" in parsed_data
    assert "vitals" in parsed_data
    assert "plan" in parsed_data

    for section, commands in parsed_data.items():
        assert all(isinstance(command, _BaseCommand) for command in commands)


def test_parse_with_unsupported_section() -> None:
    """Test that the parser does not raise an exception and discards unsupported sections."""
    parser = ScribeParser()
    transcript_with_unsupported_section = """
    Chief Complaint
    - Patient reports headache

    Unsupported Section
    - This section is not supported by the parser

    History of Present Illness
    - Headache started 3 days ago
    - Pain is throbbing
    """

    parsed_data = parser.parse(transcript_with_unsupported_section)

    assert "unsupported_section" not in parsed_data
