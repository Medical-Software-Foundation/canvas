"""Tests for consent_capture/constants.py."""

from consent_capture import constants
from consent_capture.constants import parse_statement


class TestModuleConstants:
    def test_button_constants_present(self):
        assert constants.BUTTON_TITLE == "Consent"
        assert constants.BUTTON_KEY == "COLLECT_CONSENT"
        assert constants.BUTTON_COLOR == "#c0392b"
        assert constants.NO_STATEMENT_NOTE
        assert constants.ACCEPTED_STATES == (
            "accepted",
            "accepted_via_patient_portal",
        )


class TestParseStatement:
    def test_none_returns_empty(self):
        assert parse_statement(None) == []

    def test_empty_string_returns_empty(self):
        assert parse_statement("") == []

    def test_whitespace_only_returns_empty(self):
        assert parse_statement("   \n  \t ") == []

    def test_single_line(self):
        assert parse_statement("I consent to treatment.") == [
            "I consent to treatment."
        ]

    def test_multiple_lines_become_paragraphs(self):
        raw = "First paragraph.\nSecond paragraph."
        assert parse_statement(raw) == ["First paragraph.", "Second paragraph."]

    def test_blank_lines_are_dropped(self):
        raw = "First.\n\n\nSecond.\n"
        assert parse_statement(raw) == ["First.", "Second."]

    def test_double_pipe_separator(self):
        raw = "First.||Second.||Third."
        assert parse_statement(raw) == ["First.", "Second.", "Third."]

    def test_carriage_returns_normalized(self):
        raw = "First.\r\nSecond.\rThird."
        assert parse_statement(raw) == ["First.", "Second.", "Third."]

    def test_lines_are_stripped(self):
        raw = "   Padded line.   "
        assert parse_statement(raw) == ["Padded line."]
