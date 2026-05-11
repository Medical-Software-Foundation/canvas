"""Phase C: questionnaire-backed section helpers.

Each questionnaire-backed section maps to a Canvas Questionnaire registered
via the plugin manifest. At save time we resolve the section's questionnaire
to its UUID (so `StructuredAssessmentCommand(questionnaire_id=...)` can fire)
and build a human-readable `result` summary from the form fields.
"""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.questionnaire import Questionnaire

QUESTIONNAIRE_CODE_SYSTEM = "INTERNAL"

# section_id -> (questionnaire INTERNAL code, ordered list of (field_id, label))
QUESTIONNAIRE_SECTIONS: dict[str, dict[str, Any]] = {
    "social_diet_history": {
        "code": "NUTRITION_SOCIAL_DIET",
        "fields": [
            ("appetite", "Appetite"),
            ("chew_swallow", "Chew/Swallow"),
            ("nausea_vomiting", "Nausea/Vomiting"),
            ("constipation_diarrhea", "Constipation/Diarrhea"),
            ("other_gi", "Other GI"),
            ("known_food_allergies", "Known Food Allergies"),
            ("diet_at_home", "Diet Followed at Home"),
            ("food_preferences", "Food Preferences"),
        ],
    },
    "dietary_intake": {
        "code": "NUTRITION_DIETARY_INTAKE",
        "fields": [
            ("meals_per_day", "Meals/day"),
            ("snacks_per_day", "Snacks/day"),
            ("breakfast", "Breakfast (AM)"),
            ("lunch", "Lunch (PM)"),
            ("dinner", "Dinner (PM)"),
            ("snacks", "Snacks"),
            ("fluids", "Fluids"),
            ("etoh", "ETOH"),
            ("physical_activity", "Physical activity history and limitations"),
        ],
    },
    "nutrition_diagnosis_pes": {
        "code": "NUTRITION_PES",
        "fields": [
            ("problem", "Problem"),
            ("etiology", "Etiology"),
            ("signs_symptoms", "Signs/Symptoms"),
        ],
    },
    "nfpe": {
        "code": "NUTRITION_NFPE",
        "fields": [
            ("nfpe_narrative", "NFPE Narrative"),
        ],
    },
}

# Per-process cache so we don't re-query Canvas on every save.
_id_cache: dict[str, str] = {}


def resolve_questionnaire_id(section_id: str) -> str | None:
    """Return the Canvas Questionnaire UUID for a section_id, or None if
    the section is not a questionnaire section or no matching Questionnaire
    is registered yet."""
    section = QUESTIONNAIRE_SECTIONS.get(section_id)
    if not section:
        return None

    code = section["code"]
    if code in _id_cache:
        return _id_cache[code]

    q = (
        Questionnaire.objects.filter(
            code=code, code_system=QUESTIONNAIRE_CODE_SYSTEM
        )
        .order_by("-modified")
        .first()
    )
    if q is None:
        return None

    qid = str(q.id)
    _id_cache[code] = qid
    return qid


def summarize_section(section_id: str, payload: dict) -> str:
    """Build a human-readable `result` string from the saved form fields.

    Used for `StructuredAssessmentCommand.result` so the dietician sees a
    one-glance summary in the Commands tab without expanding the questionnaire.
    """
    section = QUESTIONNAIRE_SECTIONS.get(section_id)
    if not section or not isinstance(payload, dict):
        return ""

    parts: list[str] = []
    for field_id, label in section["fields"]:
        raw = payload.get(field_id)
        if raw is None or raw == "":
            continue
        text = str(raw).strip()
        if not text:
            continue
        parts.append(f"{label}: {text}")
    return " | ".join(parts)


def reset_cache() -> None:
    """Test seam — drop the per-process Questionnaire ID cache."""
    _id_cache.clear()
