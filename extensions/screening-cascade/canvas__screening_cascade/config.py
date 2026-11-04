"""Cascade rules: the defaults, and parsing of the optional JSON override.

Everything here is pure Python so it can be tested without a database.

A rule says: when a committed questionnaire matches ``trigger`` and its total
score passes ``operator`` / ``threshold``, originate ``follow_up`` on the same
note, unless the patient already has that follow-up from the last
``cooldown_days`` days. A rule can also write the trigger's score back to the
chart with ``CreateQuestionnaireResult`` (``result``), and can pick a different
follow-up per clinician (``follow_up_by_staff``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ENABLED_VARIABLE = "SCREENING_CASCADE_ENABLED"
RULES_VARIABLE = "SCREENING_CASCADE_RULES"

TRUTHY = {"1", "true", "yes", "on"}
OPERATORS = (">=", ">", "<=", "<", "==")
DEFAULT_COOLDOWN_DAYS = 14


class RulesError(ValueError):
    """SCREENING_CASCADE_RULES is set but is not a valid rule list."""


@dataclass(frozen=True)
class Coding:
    """A questionnaire or observation coding: code system plus code."""

    code_system: str
    code: str

    def matches(self, code_system: str | None, code: str | None) -> bool:
        """Match code exactly; match the code system without regard to case."""
        return (code or "") == self.code and (code_system or "").casefold() == (
            self.code_system.casefold()
        )


@dataclass(frozen=True)
class Band:
    """A labelled score range, inclusive at both ends, used for the narrative."""

    min: float
    max: float
    label: str


@dataclass(frozen=True)
class Rule:
    """One screener -> follow-up cascade."""

    name: str
    trigger: Coding
    operator: str | None = None
    threshold: float | None = None
    follow_up: Coding | None = None
    follow_up_by_staff: dict[str, Coding] = field(default_factory=dict)
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS
    result: Coding | None = None
    bands: tuple[Band, ...] = ()

    @property
    def has_follow_up(self) -> bool:
        """True if this rule can originate anything."""
        return self.follow_up is not None or bool(self.follow_up_by_staff)


# Codes match the questionnaires Canvas provisions by default (PHQ-2 LOINC
# 58120-7, GAD-2 SNOMED 836551000000102, PHQ-9 LOINC 44249-1, GAD-7 LOINC
# 69737-5). Instances that built their own copies use other codes; override
# with SCREENING_CASCADE_RULES.
DEFAULT_RULES_JSON: list[dict[str, Any]] = [
    {
        "name": "PHQ-2 to PHQ-9",
        "trigger": {"code_system": "LOINC", "code": "58120-7"},
        "operator": ">=",
        "threshold": 3,
        "follow_up": {"code_system": "LOINC", "code": "44249-1"},
        "cooldown_days": DEFAULT_COOLDOWN_DAYS,
        "result": {"code_system": "INTERNAL", "code": "screening_cascade_phq2"},
        "bands": [
            {"min": 0, "max": 2, "label": "Negative screen"},
            {"min": 3, "max": 6, "label": "Positive screen, PHQ-9 recommended"},
        ],
    },
    {
        "name": "GAD-2 to GAD-7",
        "trigger": {"code_system": "SNOMED", "code": "836551000000102"},
        "operator": ">=",
        "threshold": 3,
        "follow_up": {"code_system": "LOINC", "code": "69737-5"},
        "cooldown_days": DEFAULT_COOLDOWN_DAYS,
        "result": {"code_system": "INTERNAL", "code": "screening_cascade_gad2"},
        "bands": [
            {"min": 0, "max": 2, "label": "Negative screen"},
            {"min": 3, "max": 6, "label": "Positive screen, GAD-7 recommended"},
        ],
    },
]


def is_enabled(secrets: dict[str, Any]) -> bool:
    """The plugin does nothing until SCREENING_CASCADE_ENABLED is truthy."""
    return str(secrets.get(ENABLED_VARIABLE) or "").strip().lower() in TRUTHY


def load_rules(secrets: dict[str, Any]) -> list[Rule]:
    """Rules from SCREENING_CASCADE_RULES if set, else the defaults.

    Raises RulesError if the override is set but invalid. The caller should
    then do nothing, not fall back to defaults the admin meant to replace.
    """
    raw = str(secrets.get(RULES_VARIABLE) or "").strip()
    if not raw:
        return parse_rules(DEFAULT_RULES_JSON)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RulesError(f"{RULES_VARIABLE} is not valid JSON: {exc}") from exc
    return parse_rules(data)


def parse_rules(data: Any) -> list[Rule]:
    """Validate a list of rule dicts. Raises RulesError naming the bad rule."""
    if not isinstance(data, list):
        raise RulesError(f"{RULES_VARIABLE} must be a JSON list of rules")
    return [_parse_rule(item, index) for index, item in enumerate(data)]


def _parse_rule(item: Any, index: int) -> Rule:
    if not isinstance(item, dict):
        raise RulesError(f"rule {index}: must be an object")
    name = str(item.get("name") or f"rule {index}")
    where = f"rule {index} ({name})"

    trigger = _coding(item.get("trigger"), f"{where} trigger")
    if trigger is None:
        raise RulesError(f"{where}: trigger is required")

    follow_up = _coding(item.get("follow_up"), f"{where} follow_up")
    by_staff_raw = item.get("follow_up_by_staff") or {}
    if not isinstance(by_staff_raw, dict):
        raise RulesError(f"{where}: follow_up_by_staff must be an object of staff id -> coding")
    by_staff: dict[str, Coding] = {}
    for staff_id, coding in by_staff_raw.items():
        parsed = _coding(coding, f"{where} follow_up_by_staff[{staff_id}]")
        if parsed is not None:
            by_staff[str(staff_id)] = parsed

    operator = item.get("operator")
    threshold = item.get("threshold")
    if follow_up is not None or by_staff:
        if operator not in OPERATORS:
            raise RulesError(f"{where}: operator must be one of {', '.join(OPERATORS)}")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise RulesError(f"{where}: threshold must be a number")

    cooldown = item.get("cooldown_days", DEFAULT_COOLDOWN_DAYS)
    if isinstance(cooldown, bool) or not isinstance(cooldown, int) or cooldown < 0:
        raise RulesError(f"{where}: cooldown_days must be a whole number of days, 0 or more")

    result = _coding(item.get("result"), f"{where} result")
    if follow_up is None and not by_staff and result is None:
        raise RulesError(f"{where}: needs a follow_up, follow_up_by_staff, or result")

    return Rule(
        name=name,
        trigger=trigger,
        operator=operator,
        threshold=float(threshold) if threshold is not None else None,
        follow_up=follow_up,
        follow_up_by_staff=by_staff,
        cooldown_days=cooldown,
        result=result,
        bands=tuple(_band(b, f"{where} bands") for b in item.get("bands") or []),
    )


def _coding(value: Any, where: str) -> Coding | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RulesError(f"{where}: must be an object with code_system and code")
    code_system = str(value.get("code_system") or "").strip()
    code = str(value.get("code") or "").strip()
    if not code_system or not code:
        raise RulesError(f"{where}: code_system and code are both required")
    return Coding(code_system=code_system, code=code)


def _band(value: Any, where: str) -> Band:
    if not isinstance(value, dict):
        raise RulesError(f"{where}: each band must be an object")
    try:
        return Band(min=float(value["min"]), max=float(value["max"]), label=str(value["label"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RulesError(f"{where}: each band needs numeric min, max and a label") from exc
