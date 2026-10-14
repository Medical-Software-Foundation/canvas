from __future__ import annotations

import pytest

from dot_phrases.text import (
    codes_in,
    fill,
    fill_ins,
    has_placeholders,
    is_valid_code,
    pronouns,
    rx_message,
    rx_problems,
    unknown_placeholders,
)

VALUES = {"first_name": "jane", "age": "67", "subject_pronoun": "she", "after_hours_line": "(555) 010-2000"}


class TestCodes:
    def test_finds_codes_that_start_a_word(self) -> None:
        assert codes_in("Plan: .fallprec and .FU2W") == ["fallprec", "fu2w"]

    @pytest.mark.parametrize("text", ["Take .5 mL daily", "e.g. take it", "see example.com", "", ".9abc"])
    def test_ignores_text_that_is_not_a_code(self, text: str) -> None:
        assert codes_in(text) == []

    @pytest.mark.parametrize("code,valid", [("metf500", True), ("a", True), ("9abc", False), ("Metf", False), ("met-f", False), ("a" * 64, True), ("a" * 65, False)])
    def test_code_rules(self, code: str, valid: bool) -> None:
        assert is_valid_code(code) is valid


class TestFill:
    def test_fills_patient_and_practice_values_and_capitalizes_sentence_starts(self) -> None:
        result = fill("{first_name} is {age}. {subject_pronoun} can call {after_hours_line}.", VALUES)
        assert result.text == "Jane is 67. She can call (555) 010-2000."
        assert result.leftovers == ()

    def test_missing_chart_value_stays_as_typed_and_is_left_to_fill(self) -> None:
        result = fill("Prefers {preferred_name}.", VALUES)
        assert result.text == "Prefers {preferred_name}."
        assert result.leftovers == ("{preferred_name}",)

    def test_unanswered_choices_and_blanks_become_brackets(self) -> None:
        result = fill("{pick side: right | left} knee for {blank duration}. Reports ***.", VALUES)
        assert result.text == "[right / left] knee for [duration]. Reports ***."
        assert result.leftovers == ("[right / left]", "[duration]")

    def test_answers_fill_choices_blanks_and_stars_in_order(self) -> None:
        result = fill("{pick side: right | left} knee for {blank duration}. Reports ***.", VALUES, ["left", "2 weeks", "stiffness"])
        assert result.text == "left knee for 2 weeks. Reports stiffness."
        assert result.leftovers == ()

    def test_fill_ins_lists_what_the_panel_asks_for(self) -> None:
        asks = fill_ins("{first_name} {pick side: right | left} {blank duration} *** ***")
        assert [(a.kind, a.label, a.options) for a in asks] == [
            ("pick", "side", ("right", "left")),
            ("blank", "duration", ()),
            ("blank", "Blank 1", ()),
            ("blank", "Blank 2", ()),
        ]


class TestPronouns:
    @pytest.mark.parametrize("value,expected", [("she/her", ("she", "her", "her")), ("He / Him", ("he", "him", "his")), ("they/them", ("they", "them", "their"))])
    def test_recognized_values(self, value: str, expected: tuple[str, str, str]) -> None:
        assert pronouns(value) == expected

    @pytest.mark.parametrize("value", [None, "", "ze/zir", "any"])
    def test_anything_else_is_left_for_the_provider(self, value: str | None) -> None:
        assert pronouns(value) is None


class TestRules:
    def test_unknown_placeholders(self) -> None:
        assert unknown_placeholders("{first_name} {clinic_fax} {frist_name}", {"clinic_fax"}) == ["{frist_name}"]

    def test_has_placeholders(self) -> None:
        assert has_placeholders("Reports ***")
        assert not has_placeholders("Take 1 tablet")

    def test_note_to_pharmacist_limit_is_210(self) -> None:
        assert rx_problems(210, "x" * 210) == []
        assert rx_problems(210, "x" * 211) == ["over 210 characters"]

    def test_pharmacy_text_is_one_line_of_plain_characters_without_placeholders(self) -> None:
        assert rx_problems(1000, "Take 1\nwith food") == ["has a line break"]
        assert rx_problems(1000, "Take ½ tablet") == ["has special characters"]
        assert rx_problems(1000, "Take for {blank days}") == ["has placeholders"]

    def test_keyboard_symbols_like_at_and_hash_are_allowed(self) -> None:
        assert rx_problems(1000, "Call #2 @ 9am, 50% off & more ~ok") == []

    def test_editor_message_names_the_field_the_problem_and_the_fix(self) -> None:
        assert rx_message("Sig", 1000, "Take 1\nwith food") == "Can't use in the Sig: it has a line break. Remove it, or uncheck Use in Sig."
        assert rx_message("Note to pharmacist", 210, "x" * 243) == (
            "Can't use in the note to pharmacist: it's over 210 characters (243). Shorten it, or uncheck Use in note to pharmacist."
        )
        assert rx_message("Sig", 1000, "Take ½ tab at 98.6°, take ½ again") == (
            "Can't use in the Sig: it has special characters (½, °). Replace them, or uncheck Use in Sig."
        )
        assert rx_message("Sig", 1000, "Take 1 tablet") == ""

    def test_editor_message_with_several_problems_says_fix_these(self) -> None:
        assert rx_message("Sig", 10, "Take {blank days} days") == (
            "Can't use in the Sig: it's over 10 characters (22) and it has placeholders. Fix these, or uncheck Use in Sig."
        )
