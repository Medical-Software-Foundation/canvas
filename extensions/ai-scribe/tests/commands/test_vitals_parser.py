import pytest
from ai_scribe import parsers
from ai_scribe.parsers.commands.vitals import VitalsParser

from canvas_sdk.commands.commands.vitals import VitalsCommand


@pytest.fixture
def complete_vitals_example() -> parsers.ParsedContent:
    """Return a complete example of vitals."""
    return parsers.ParsedContent(
        arguments=[
            "Weight: 244 lbs",
            "Height: 5'10\"",
            "Heart rate: 80",
            "Oxygen saturation: 94%",
            "Blood pressure: 167/106",
        ]
    )


@pytest.fixture
def unsupported_vitals_example() -> parsers.ParsedContent:
    """Return an example of vitals with unsupported values."""
    return parsers.ParsedContent(arguments=["Temperature: 98.6 F", "Respiratory rate: 16"])


def test_parse_vitals(complete_vitals_example: parsers.ParsedContent) -> None:
    """Test the `parse` method of `VitalsParser` with a complete example."""
    parser = VitalsParser()
    parsed_commands = parser.parse(complete_vitals_example)

    assert len(parsed_commands) > 0
    assert all(isinstance(cmd, VitalsCommand) for cmd in parsed_commands)
    assert parsed_commands[0].height == 70
    assert parsed_commands[0].weight_lbs == 244
    assert parsed_commands[0].pulse == 80
    assert parsed_commands[0].oxygen_saturation == 94
    assert parsed_commands[0].blood_pressure_systole == 167
    assert parsed_commands[0].blood_pressure_diastole == 106


def test_parse_unsupported_vitals(unsupported_vitals_example: parsers.ParsedContent) -> None:
    """Test the `parse` method of `VitalsParser` with unsupported vitals."""
    parser = VitalsParser()
    parsed_commands = parser.parse(unsupported_vitals_example)

    assert len(parsed_commands) == 1
    assert all(isinstance(cmd, VitalsCommand) for cmd in parsed_commands)
    assert parsed_commands[0].height is None
    assert parsed_commands[0].weight_lbs is None
    assert parsed_commands[0].pulse is None
    assert parsed_commands[0].oxygen_saturation is None
    assert parsed_commands[0].blood_pressure_systole is None
    assert parsed_commands[0].blood_pressure_diastole is None


def test_parse_height_valid() -> None:
    """Test the `parse_height` method of `VitalsParser` with valid inputs."""
    parser = VitalsParser()
    assert parser.parse_height("5'10\"") == 70
    assert parser.parse_height("6'0\"") == 72


def test_parse_height_invalid() -> None:
    """Test the `parse_height` method of `VitalsParser` with invalid inputs."""
    parser = VitalsParser()
    assert parser.parse_height("invalid") is None


def test_parse_weight_valid() -> None:
    """Test the `parse_weight` method of `VitalsParser` with valid inputs."""
    parser = VitalsParser()
    assert parser.parse_weight("150 lbs") == 150
    assert parser.parse_weight("200 lbs") == 200


def test_parse_weight_invalid() -> None:
    """Test the `parse_weight` method of `VitalsParser` with invalid inputs."""
    parser = VitalsParser()
    assert parser.parse_weight("invalid") is None


def test_parse_blood_pressure_valid() -> None:
    """Test the `parse_blood_pressure` method of `VitalsParser` with valid inputs."""
    parser = VitalsParser()
    assert parser.parse_blood_pressure("120/80") == {
        "blood_pressure_systole": 120,
        "blood_pressure_diastole": 80,
    }


def test_parse_blood_pressure_invalid() -> None:
    """Test the `parse_blood_pressure` method of `VitalsParser` with invalid inputs."""
    parser = VitalsParser()
    assert parser.parse_blood_pressure("invalid") == {}
