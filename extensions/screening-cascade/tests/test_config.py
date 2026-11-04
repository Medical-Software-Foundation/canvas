"""Rule parsing and the on/off switch."""

import json

import pytest

from canvas__screening_cascade.config import (
    Coding,
    is_enabled,
    load_rules,
    parse_rules,
)


@pytest.mark.parametrize("value", ["true", "TRUE", " on ", "1", "yes"])
def test_enabled_values(value: str) -> None:
    assert is_enabled({"SCREENING_CASCADE_ENABLED": value})


@pytest.mark.parametrize("value", [None, "", "false", "0", "off", "enabled please"])
def test_off_by_default_and_for_anything_else(value: str | None) -> None:
    assert not is_enabled({"SCREENING_CASCADE_ENABLED": value})
    assert not is_enabled({})


def test_defaults_are_phq2_to_phq9_and_gad2_to_gad7() -> None:
    rules = load_rules({})
    assert [r.name for r in rules] == ["PHQ-2 to PHQ-9", "GAD-2 to GAD-7"]
    phq, gad = rules
    assert phq.trigger == Coding("LOINC", "58120-7")
    assert phq.follow_up == Coding("LOINC", "44249-1")
    assert (phq.operator, phq.threshold, phq.cooldown_days) == (">=", 3.0, 14)
    assert gad.trigger == Coding("SNOMED", "836551000000102")
    assert gad.follow_up == Coding("LOINC", "69737-5")
    assert phq.result == Coding("INTERNAL", "screening_cascade_phq2")


def test_override_replaces_defaults() -> None:
    override = [
        {
            "name": "PHQ-9 to MADRS",
            "trigger": {"code_system": "LOINC", "code": "44249-1"},
            "operator": "<=",
            "threshold": 20,
            "follow_up": {"code_system": "INTERNAL", "code": "MADRS"},
            "follow_up_by_staff": {"abc123": {"code_system": "INTERNAL", "code": "HAMD"}},
            "cooldown_days": 0,
        }
    ]
    rules = load_rules({"SCREENING_CASCADE_RULES": json.dumps(override)})
    assert len(rules) == 1
    rule = rules[0]
    assert rule.follow_up_by_staff == {"abc123": Coding("INTERNAL", "HAMD")}
    assert rule.cooldown_days == 0
    assert rule.result is None


def test_score_only_rule_needs_no_threshold() -> None:
    (rule,) = parse_rules(
        [
            {
                "name": "AUDIT-C score",
                "trigger": {"code_system": "LOINC", "code": "72109-2"},
                "result": {"code_system": "INTERNAL", "code": "auditc"},
            }
        ]
    )
    assert not rule.has_follow_up


def test_bad_json_raises() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        load_rules({"SCREENING_CASCADE_RULES": "[{"})


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"name": "x"}, "trigger is required"),
        ({"trigger": {"code_system": "LOINC"}}, "code_system and code"),
        (
            {
                "trigger": {"code_system": "L", "code": "1"},
                "follow_up": {"code_system": "L", "code": "2"},
            },
            "operator",
        ),
        (
            {
                "trigger": {"code_system": "L", "code": "1"},
                "follow_up": {"code_system": "L", "code": "2"},
                "operator": ">=",
                "threshold": "3",
            },
            "threshold must be a number",
        ),
        (
            {
                "trigger": {"code_system": "L", "code": "1"},
                "follow_up": {"code_system": "L", "code": "2"},
                "operator": ">=",
                "threshold": 3,
                "cooldown_days": -1,
            },
            "cooldown_days",
        ),
        ({"trigger": {"code_system": "L", "code": "1"}}, "needs a follow_up"),
        (
            {
                "trigger": {"code_system": "L", "code": "1"},
                "result": {"code_system": "I", "code": "r"},
                "bands": [{"min": 0}],
            },
            "bands",
        ),
    ],
)
def test_invalid_rules_name_the_problem(rule: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_rules([rule])


def test_rules_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="JSON list"):
        parse_rules({"name": "x"})


def test_coding_match_ignores_code_system_case_only() -> None:
    coding = Coding("LOINC", "44249-1")
    assert coding.matches("loinc", "44249-1")
    assert not coding.matches("LOINC", "44249-2")
    assert not coding.matches(None, None)
