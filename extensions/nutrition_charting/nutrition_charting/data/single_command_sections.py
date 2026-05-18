"""Phase D: registry of single-command sections.

These are sections that emit exactly one Canvas command on save (vs. the
questionnaire-backed sections in `questionnaires.py` which emit a
StructuredAssessmentCommand, or the multi-command sections in
`multi_command_sections.py` which emit 0..N commands of the same class).
Each entry declares:

  - `command_class`     — the canvas_sdk.commands class to instantiate
  - `fields`            — ordered list of (field_id, label, kind) for rendering
  - `build_kwargs`      — pure function (payload) -> command kwargs (excluding
                          note_uuid + command_uuid, which the API layer adds)
  - `is_emit_ready`     — pure function (payload) -> bool, used to skip emission
                          when the form is empty (e.g. no follow-up date set)

Pass 1 sections: Estimated Nutrition Requirements, Follow-up appointment.
Pass 2 sections: Counseling narrative, Recommended labs, Recommended
supplementation, Monitor at team meeting (Task, gated by checkbox).

Recommended labs deviates from the spec's "LabOrder per lab" because
LabOrderCommand validates that lab_partner + tests_order_codes match a real
configured partner; recommendations to the team aren't tied to one. We emit a
formatted PlanCommand titled "Recommended Labs" instead — same structured-data
queryability, no per-customer lab-partner config required.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from canvas_sdk.commands import FollowUpCommand, PlanCommand, TaskCommand
from canvas_sdk.commands.commands.task import AssigneeType


def _parse_date(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def _build_requirements_plan_kwargs(payload: dict) -> dict[str, Any]:
    """Format the four nutrition-requirement fields into a single Plan narrative."""
    if not payload:
        return {}
    rows = [
        ("Calories", payload.get("calories"), "kcal/day"),
        ("Protein", payload.get("protein"), "g/day"),
        ("Carbohydrates", payload.get("carbohydrates"), "g/day"),
        ("Fluid", payload.get("fluid"), "mL/day"),
    ]
    lines = [
        f"- {label}: {str(value).strip()} {unit}"
        for label, value, unit in rows
        if value not in (None, "")
    ]
    if not lines:
        return {}
    narrative = "Estimated Nutrition Requirements\n" + "\n".join(lines)
    return {"narrative": narrative}


def _requirements_emit_ready(payload: dict) -> bool:
    return bool(_build_requirements_plan_kwargs(payload))


def _build_followup_kwargs(payload: dict) -> dict[str, Any]:
    if not payload:
        return {}
    requested_date = _parse_date(payload.get("follow_up_date"))
    if not requested_date:
        return {}
    kwargs: dict[str, Any] = {"requested_date": requested_date}
    comment = payload.get("follow_up_comment")
    if isinstance(comment, str) and comment.strip():
        kwargs["comment"] = comment.strip()
    return kwargs


def _followup_emit_ready(payload: dict) -> bool:
    return _parse_date((payload or {}).get("follow_up_date")) is not None


# ---- Pass 2 builders ------------------------------------------------------

# Canonical recommended-lab options confirmed with the customer (spec sec. 7).
# The form posts a list of selected canonical keys plus optional "other" entries.
RECOMMENDED_LAB_OPTIONS: list[tuple[str, str]] = [
    ("lipid_panel", "Lipid panel"),
    ("a1c", "A1c / HbA1c"),
    ("bmp", "BMP (basic metabolic panel)"),
    ("cbc", "CBC"),
    ("vitamin_d", "Vitamin D 25-OH"),
    ("ferritin", "Ferritin"),
    ("magnesium", "Magnesium"),
    ("vitamin_b12", "Vitamin B12"),
]
RECOMMENDED_LAB_LABELS: dict[str, str] = dict(RECOMMENDED_LAB_OPTIONS)


def _normalize_str_list(raw: Any) -> list[str]:
    """Accept a list-of-strings or a newline-separated string. Trims and drops blanks."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.splitlines()
    elif isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        return []
    return [item.strip() for item in items if isinstance(item, str) and item.strip()]


def _build_counseling_plan_kwargs(payload: dict) -> dict[str, Any]:
    """Free-text counseling narrative -> single Plan command."""
    if not payload:
        return {}
    text = (payload.get("counseling_narrative") or "").strip()
    if not text:
        return {}
    return {"narrative": f"Counseling\n{text}"}


def _counseling_emit_ready(payload: dict) -> bool:
    return bool((payload or {}).get("counseling_narrative", "").strip())


def _build_recommended_labs_kwargs(payload: dict) -> dict[str, Any]:
    """Multi-select canonical labs + free-text "other" -> bulleted Plan narrative."""
    if not payload:
        return {}
    selected_keys = _normalize_str_list(payload.get("selected"))
    other_lines = _normalize_str_list(payload.get("other"))

    items: list[str] = []
    for key in selected_keys:
        items.append(RECOMMENDED_LAB_LABELS.get(key, key))
    items.extend(other_lines)

    if not items:
        return {}

    narrative = "Recommended Labs\n" + "\n".join(f"- {item}" for item in items)
    return {"narrative": narrative}


def _recommended_labs_emit_ready(payload: dict) -> bool:
    return bool(_build_recommended_labs_kwargs(payload))


def _build_recommended_supplementation_kwargs(payload: dict) -> dict[str, Any]:
    """Free-text supplementation recommendations -> single Plan command."""
    if not payload:
        return {}
    text = (payload.get("supplementation") or "").strip()
    if not text:
        return {}
    return {"narrative": f"Recommended Supplementation\n{text}"}


def _recommended_supplementation_emit_ready(payload: dict) -> bool:
    return bool((payload or {}).get("supplementation", "").strip())


def _build_monitor_team_meeting_kwargs(payload: dict) -> dict[str, Any]:
    """Gated Task for "monitor per team meeting".

    The checkbox alone enables the Task; an optional `comment` becomes the
    Task's comment. We default the assignee to "unassigned" — the team will
    pick up the task in their team-meeting queue and assign as needed.
    """
    if not payload or not _is_truthy(payload.get("monitor")):
        return {}
    kwargs: dict[str, Any] = {
        "title": "Nutrition: Monitor at next team meeting",
        "assign_to": {"to": AssigneeType.UNASSIGNED},
    }
    comment = payload.get("comment")
    if isinstance(comment, str) and comment.strip():
        kwargs["comment"] = comment.strip()
    return kwargs


def _monitor_team_meeting_emit_ready(payload: dict) -> bool:
    return _is_truthy((payload or {}).get("monitor"))


def _is_truthy(value: Any) -> bool:
    """Accept the form's checkbox encoding ('on', 'true', True, '1') as truthy."""
    if value is True:
        return True
    if value in (False, None, ""):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "on", "yes", "1"}
    return bool(value)


SINGLE_COMMAND_SECTIONS: dict[str, dict[str, Any]] = {
    "estimated_nutrition_requirements": {
        "title": "Estimated Nutrition Requirements",
        "command_class": PlanCommand,
        "fields": [
            ("calories", "Calories (kcal/day)", "number"),
            ("protein", "Protein (g/day)", "number"),
            ("carbohydrates", "Carbohydrates (g/day)", "number"),
            ("fluid", "Fluid (mL/day)", "number"),
        ],
        "build_kwargs": _build_requirements_plan_kwargs,
        "is_emit_ready": _requirements_emit_ready,
    },
    "counseling_narrative": {
        "title": "Intervention: Counseling Narrative",
        "command_class": PlanCommand,
        "fields": [
            ("counseling_narrative", "Counseling narrative", "textarea"),
        ],
        "build_kwargs": _build_counseling_plan_kwargs,
        "is_emit_ready": _counseling_emit_ready,
    },
    "follow_up_appointment": {
        "title": "Monitoring & Evaluation: Follow-up",
        "command_class": FollowUpCommand,
        "fields": [
            ("follow_up_date", "Follow-up appointment date", "date"),
            ("follow_up_comment", "Reason / comment", "textarea"),
        ],
        "build_kwargs": _build_followup_kwargs,
        "is_emit_ready": _followup_emit_ready,
    },
    "recommended_labs": {
        "title": "Coordination of Care: Recommended Labs",
        "command_class": PlanCommand,
        # Multi-select + "other" textarea — kept on a single section so the
        # whole list emits as one Plan command.
        "fields": [
            ("selected", "Selected labs", "checklist"),
            ("other", "Other labs (one per line)", "textarea"),
        ],
        "checklist_options": RECOMMENDED_LAB_OPTIONS,
        "build_kwargs": _build_recommended_labs_kwargs,
        "is_emit_ready": _recommended_labs_emit_ready,
    },
    "recommended_supplementation": {
        "title": "Coordination of Care: Recommended Supplementation",
        "command_class": PlanCommand,
        "fields": [
            ("supplementation", "Recommended supplementation", "textarea"),
        ],
        "build_kwargs": _build_recommended_supplementation_kwargs,
        "is_emit_ready": _recommended_supplementation_emit_ready,
    },
    "monitor_team_meeting": {
        "title": "Coordination of Care: Monitor at Team Meeting",
        "command_class": TaskCommand,
        "fields": [
            ("monitor", "Monitor at next team meeting", "checkbox"),
            ("comment", "Comment (optional)", "textarea"),
        ],
        "build_kwargs": _build_monitor_team_meeting_kwargs,
        "is_emit_ready": _monitor_team_meeting_emit_ready,
    },
}


def get_section(section_id: str) -> dict[str, Any] | None:
    return SINGLE_COMMAND_SECTIONS.get(section_id)


# Type alias for the build_kwargs callable so callers can satisfy mypy.
BuildKwargs = Callable[[dict], dict[str, Any]]
