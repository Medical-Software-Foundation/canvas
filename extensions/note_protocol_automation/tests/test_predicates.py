"""Pure predicate evaluation — no DB, exhaustive over signals/operators/edges."""

from typing import Any

from note_protocol_automation.lib.predicates import evaluate
from note_protocol_automation.lib.types import LabReading, PatientSignals


def _signals(**kw: Any) -> PatientSignals:
    """Build a PatientSignals with sensible empty defaults, overriding via kwargs."""
    base: dict[str, Any] = dict(
        icd10_codes=frozenset(), age=None, sex="", lab_values={}, care_team_roles=frozenset()
    )
    base.update(kw)
    return PatientSignals(**base)


def test_condition_has_prefix_matches_active_icd10() -> None:
    """has_prefix matches when any active ICD-10 code starts with the value."""
    s = _signals(icd10_codes=frozenset({"I10", "E11.9"}))
    assert evaluate({"signal": "condition", "operator": "has_prefix", "value": "I1"}, s) is True
    assert evaluate({"signal": "condition", "operator": "has_prefix", "value": "J45"}, s) is False


def test_condition_not_has() -> None:
    """not_has is true only when no active code equals the value."""
    s = _signals(icd10_codes=frozenset({"E11.9"}))
    assert evaluate({"signal": "condition", "operator": "not_has", "value": "I10"}, s) is True
    assert evaluate({"signal": "condition", "operator": "not_has", "value": "E11.9"}, s) is False


def test_age_operators() -> None:
    """age supports >=, <=, ==, and between (inclusive)."""
    s = _signals(age=66)
    assert evaluate({"signal": "age", "operator": ">=", "value": 18}, s) is True
    assert evaluate({"signal": "age", "operator": "<=", "value": 65}, s) is False
    assert evaluate({"signal": "age", "operator": "between", "value": [60, 70]}, s) is True


def test_age_missing_is_false() -> None:
    """A missing age never satisfies an age predicate."""
    assert evaluate({"signal": "age", "operator": ">=", "value": 18}, _signals(age=None)) is False


def test_sex_equality() -> None:
    """sex == compares case-insensitively against sex_at_birth."""
    assert evaluate({"signal": "sex", "operator": "==", "value": "F"}, _signals(sex="F")) is True
    assert evaluate({"signal": "sex", "operator": "==", "value": "M"}, _signals(sex="F")) is False


def test_lab_value_threshold_and_recency() -> None:
    """lab_value compares the numeric reading AND enforces within_days recency."""
    s = _signals(lab_values={"33914-3": LabReading(value=40.0, days_old=90)})
    p = {
        "signal": "lab_value",
        "operator": "<",
        "value": {"loinc": "33914-3", "threshold": 45, "within_days": 180},
    }
    assert evaluate(p, s) is True
    stale = _signals(lab_values={"33914-3": LabReading(value=40.0, days_old=400)})
    assert evaluate(p, stale) is False  # too old
    missing = _signals(lab_values={})
    assert evaluate(p, missing) is False  # no reading


def test_care_team_role() -> None:
    """has_role is true when the role_code is in the active membership set."""
    s = _signals(care_team_roles=frozenset({"nurse_practitioner"}))
    assert (
        evaluate(
            {"signal": "care_team_role", "operator": "has_role", "value": "nurse_practitioner"}, s
        )
        is True
    )
    assert (
        evaluate({"signal": "care_team_role", "operator": "has_role", "value": "physician"}, s)
        is False
    )


def test_unknown_signal_is_false() -> None:
    """An unknown signal type fails closed (never inserts on a malformed rule)."""
    assert evaluate({"signal": "bogus", "operator": "==", "value": 1}, _signals()) is False
