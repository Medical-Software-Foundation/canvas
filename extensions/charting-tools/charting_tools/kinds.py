"""The three things the builder makes, and which commands each may hold.

Sections are Canvas's own note sections for each command (home-app's
``noteSection`` on each command type), so "plan" here means exactly what the
note's Plan section shows.
"""

from typing import Any

TEMPLATE = "template"
QUICKPICK = "quickpick"
ORDER_SET = "order_set"
RULE = "rule"
KINDS = (TEMPLATE, QUICKPICK, ORDER_SET, RULE)
# Every kind but note templates, for queries that want templates (or rows saved
# before kinds existed, whose kind is NULL).
NON_TEMPLATE_KINDS = (QUICKPICK, ORDER_SET, RULE)

KIND_LABELS = {TEMPLATE: "Note template", QUICKPICK: "Quickpick", ORDER_SET: "Order set", RULE: "Rule"}

ASSESSMENT = "assessment"
PLAN = "plan"
PROCEDURES = "procedures"

SECTION_BY_COMMAND = {
    "reasonForVisit": "subjective",
    "hpi": "subjective",
    "ros": "subjective",
    "questionnaire": "subjective",
    "exam": "objective",
    "vitals": "objective",
    "diagnose": ASSESSMENT,
    "assess": ASSESSMENT,
    "updateDiagnosis": ASSESSMENT,
    "resolveCondition": ASSESSMENT,
    "structuredAssessment": ASSESSMENT,
    "pocLabTest": ASSESSMENT,
    "plan": PLAN,
    "instruct": PLAN,
    "goal": PLAN,
    "updateGoal": PLAN,
    "closeGoal": PLAN,
    "followUp": PLAN,
    "task": PLAN,
    "labOrder": PLAN,
    "imagingOrder": PLAN,
    "orderDme": PLAN,
    "refer": PLAN,
    "prescribe": PLAN,
    "refill": PLAN,
    "adjustPrescription": PLAN,
    "stopMedication": PLAN,
    "perform": PROCEDURES,
    "immunize": PROCEDURES,
    "medicationStatement": "history",
    "allergy": "history",
    "removeAllergy": "history",
    "medicalHistory": "history",
    "surgicalHistory": "history",
    "familyHistory": "history",
    "immunizationStatement": "history",
}

# None means every command in the catalog.
ALLOWED_SECTIONS: dict[str, tuple[str, ...] | None] = {
    TEMPLATE: None,
    QUICKPICK: (PLAN, PROCEDURES),
    ORDER_SET: (ASSESSMENT, PLAN, PROCEDURES),
    RULE: None,
}


def kind_of(template: Any) -> str:
    """A row's kind; rows saved before kinds existed are templates."""
    kind = getattr(template, "kind", None)
    return kind if kind in KINDS else TEMPLATE


def allows_command(kind: str, schema_key: str) -> bool:
    """Whether a command type may be added to this kind."""
    sections = ALLOWED_SECTIONS[kind]
    return sections is None or SECTION_BY_COMMAND.get(schema_key) in sections


def max_commands(kind: str, default: int) -> int:
    """A quickpick is exactly one command."""
    return 1 if kind == QUICKPICK else default


def uses_diagnoses(kind: str) -> bool:
    """Quickpicks and order sets carry a diagnosis list; templates don't."""
    return kind in (QUICKPICK, ORDER_SET)
