"""Unit tests for vanta_lab_orders.aoe.parse_aoe_answers.

Pure function — no DB, no fixtures.
"""

from __future__ import annotations

from vanta_lab_orders.aoe import parse_aoe_answers


def test_empty_input_returns_empty_dict() -> None:
    assert parse_aoe_answers({}) == {}


def test_none_input_returns_empty_dict() -> None:
    # Command.data can be None/empty; must not raise.
    assert parse_aoe_answers(None) == {}


def test_non_dict_input_returns_empty_dict() -> None:
    # A corrupt/legacy JSONField could deserialize to a non-dict; must not raise.
    assert parse_aoe_answers("not-a-dict") == {}
    assert parse_aoe_answers(["aoes|Derm-ID|DERMSOU"]) == {}


def test_single_answer_grouped_by_test_code() -> None:
    data = {"aoes|Derm-ID|DERMSOU": "DRMSWB"}
    assert parse_aoe_answers(data) == {"Derm-ID": [("DERMSOU", "DRMSWB")]}


def test_multiple_questions_same_test_preserve_order() -> None:
    data = {
        "aoes|Derm-ID|LSTALL": "Penicillin",
        "aoes|Derm-ID|DERMSOU": "DRMSWB",
    }
    result = parse_aoe_answers(data)
    assert result == {
        "Derm-ID": [("LSTALL", "Penicillin"), ("DERMSOU", "DRMSWB")]
    }


def test_answers_routed_to_correct_test() -> None:
    data = {
        "aoes|Derm-ID|DERMSOU": "DRMSWB",
        "aoes|Gastro-ID|GASSOU": "RECTSTL",
    }
    result = parse_aoe_answers(data)
    assert result == {
        "Derm-ID": [("DERMSOU", "DRMSWB")],
        "Gastro-ID": [("GASSOU", "RECTSTL")],
    }


def test_non_aoe_keys_ignored() -> None:
    data = {
        "comment": "please process",
        "lab_partner": {"text": "Vanta Diagnostics"},
        "aoes|Derm-ID|DERMSOU": "DRMSWB",
    }
    assert parse_aoe_answers(data) == {"Derm-ID": [("DERMSOU", "DRMSWB")]}


def test_malformed_aoe_keys_ignored() -> None:
    # Wrong number of segments — must not raise, must not be included.
    data = {
        "aoes|Derm-ID": "missing-question-segment",
        "aoes|Derm-ID|DERMSOU|extra": "too-many-segments",
        "aoes|Derm-ID|DERMSOU": "DRMSWB",
    }
    assert parse_aoe_answers(data) == {"Derm-ID": [("DERMSOU", "DRMSWB")]}


def test_blank_and_none_answers_skipped() -> None:
    data = {
        "aoes|Derm-ID|LSTALL": "",
        "aoes|Derm-ID|SMPLOC": "   ",
        "aoes|Derm-ID|DERMSOU": None,
        "aoes|Derm-ID|SKMCAP": "No",
    }
    assert parse_aoe_answers(data) == {"Derm-ID": [("SKMCAP", "No")]}


def test_test_code_with_all_answers_blank_is_omitted() -> None:
    data = {"aoes|Derm-ID|LSTALL": "", "aoes|Derm-ID|SMPLOC": None}
    assert parse_aoe_answers(data) == {}


def test_non_string_answer_coerced_to_string() -> None:
    data = {"aoes|Derm-ID|SKMCAP": True}
    assert parse_aoe_answers(data) == {"Derm-ID": [("SKMCAP", "True")]}
