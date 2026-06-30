"""Rule matching: AND predicates per rule; union+dedupe commands across matches,
ordered by (priority, position). Pure — no DB."""

from note_protocol_automation.lib.matching import matched_command_keys
from note_protocol_automation.lib.types import PatientSignals


def _s(**kw: object) -> PatientSignals:
    """Build a PatientSignals with empty defaults, overriding via kwargs."""
    base: dict = dict(
        icd10_codes=frozenset(),
        age=None,
        sex="",
        lab_values={},
        care_team_roles=frozenset(),
    )
    base.update(kw)
    return PatientSignals(**base)


def test_only_fully_matching_rules_contribute_and_dedupe() -> None:
    """A rule fires only if ALL its predicates pass; command keys are deduped, ordered."""
    rules = [
        {
            "priority": 0,
            "predicates": [{"signal": "age", "operator": ">=", "value": 18}],
            "commands": ["diagnose", "plan"],
        },
        {
            "priority": 1,
            "predicates": [{"signal": "sex", "operator": "==", "value": "M"}],
            "commands": ["plan", "goal"],  # won't match (sex F)
        },
        {
            "priority": 2,
            "predicates": [{"signal": "age", "operator": ">=", "value": 65}],
            "commands": ["goal"],
        },
    ]
    out = matched_command_keys(rules, _s(age=66, sex="F"))
    assert out == ["diagnose", "plan", "goal"]  # rule0 then rule2; "plan" not duplicated


def test_no_matches_returns_empty() -> None:
    """No rule matches -> empty list."""
    rules = [
        {
            "priority": 0,
            "predicates": [{"signal": "age", "operator": ">=", "value": 99}],
            "commands": ["diagnose"],
        }
    ]
    assert matched_command_keys(rules, _s(age=40)) == []


def test_match_any_fires_when_one_predicate_passes() -> None:
    """match='any' fires the rule when at least one predicate passes; the same
    rule under the default match='all' would NOT fire (the second predicate fails)."""
    rule_template = {
        "priority": 0,
        "predicates": [
            {"signal": "age", "operator": ">=", "value": 18},  # passes (age 40)
            {"signal": "sex", "operator": "==", "value": "M"},  # fails (sex F)
        ],
        "commands": ["diagnose"],
    }
    signals = _s(age=40, sex="F")

    any_rule = {**rule_template, "match": "any"}
    assert matched_command_keys([any_rule], signals) == ["diagnose"]

    all_rule = {**rule_template, "match": "all"}
    assert matched_command_keys([all_rule], signals) == []


def test_match_any_with_no_predicates_does_not_fire() -> None:
    """match='any' over zero predicates never fires (any([]) is False), unlike the
    default match='all' where a predicate-less rule matches every note."""
    empty_any = {"priority": 0, "match": "any", "predicates": [], "commands": ["plan"]}
    assert matched_command_keys([empty_any], _s()) == []

    empty_all = {"priority": 0, "match": "all", "predicates": [], "commands": ["plan"]}
    assert matched_command_keys([empty_all], _s()) == ["plan"]
