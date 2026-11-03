"""Pure scoring: totals, thresholds, narratives."""

import pytest

from screening_cascade.config import load_rules, parse_rules
from screening_cascade.scoring import narrative, passes, total_score


def test_total_of_complete_questionnaire() -> None:
    assert total_score([(1, "2"), (2, "1")], {1, 2}) == 3.0


def test_partial_questionnaire_has_no_score() -> None:
    assert total_score([(1, "3")], {1, 2}) is None


def test_non_numeric_value_has_no_score() -> None:
    assert total_score([(1, "often"), (2, "1")], {1, 2}) is None


def test_unscored_questions_are_ignored_and_blank_value_counts_zero() -> None:
    assert total_score([(1, "2"), (2, ""), (99, "text answer")], {1, 2}) == 2.0


def test_questionnaire_with_no_scorable_questions_has_no_score() -> None:
    assert total_score([], set()) is None


@pytest.mark.parametrize(("score", "expected"), [(2, False), (3, True), (6, True)])
def test_phq2_threshold(score: int, expected: bool) -> None:
    phq = load_rules({})[0]
    assert passes(phq, score) is expected


@pytest.mark.parametrize(
    ("operator", "score", "expected"),
    [("<=", 20, True), ("<=", 21, False), ("<", 20, False), (">", 20, False), ("==", 20, True)],
)
def test_other_operators(operator: str, score: int, expected: bool) -> None:
    (rule,) = parse_rules(
        [
            {
                "trigger": {"code_system": "L", "code": "1"},
                "follow_up": {"code_system": "L", "code": "2"},
                "operator": operator,
                "threshold": 20,
            }
        ]
    )
    assert passes(rule, score) is expected


def test_score_only_rule_never_passes() -> None:
    (rule,) = parse_rules(
        [
            {
                "trigger": {"code_system": "L", "code": "1"},
                "result": {"code_system": "I", "code": "r"},
            }
        ]
    )
    assert passes(rule, 100) is False


def test_narrative_uses_band() -> None:
    phq = load_rules({})[0]
    assert narrative(phq, 4.0) == "Score: 4. Positive screen, PHQ-9 recommended."
    assert narrative(phq, 1.0) == "Score: 1. Negative screen."


def test_narrative_without_band() -> None:
    (rule,) = parse_rules(
        [
            {
                "trigger": {"code_system": "L", "code": "1"},
                "result": {"code_system": "I", "code": "r"},
            }
        ]
    )
    assert narrative(rule, 7.5) == "Score: 7.5."


def test_score_outside_every_band_gets_no_label() -> None:
    (rule,) = parse_rules(
        [
            {
                "trigger": {"code_system": "L", "code": "1"},
                "operator": ">=",
                "threshold": 2.5,
                "follow_up": {"code_system": "L", "code": "2"},
                "bands": [
                    {"min": 0, "max": 2, "label": "Low"},
                    {"min": 3, "max": 6, "label": "High"},
                ],
            }
        ]
    )
    assert narrative(rule, 2.5) == "Score: 2.5."
    assert narrative(rule, 7) == "Score: 7."
