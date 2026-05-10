"""Phase E: assemble the printable Nutrition Note payload from saved form
state + Canvas data models.

Pure data assembly — no HTML, no Effects. Output is a JSON-serializable dict
the template renderer can consume. Spec section 5 enumerates the fields and
their order.

Why read from form_state and not from emitted Canvas Commands: form_state is
the canonical source we control end-to-end. Commands are a side-effect; some
fields (UBW, IBW, recommended-labs canonical-key list) never become commands
at all but still belong on the print. For Vitals (anthropometrics) and the
chart-review reference data we delegate to `build_chart_review`, which reads
the same Observations + Conditions + Medications the auto-populate flow uses.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.patient import Patient
from logger import log

from nutrition_charting.data.form_state import get_form_state
from nutrition_charting.data.medical_chart_review import build_chart_review
from nutrition_charting.data.multi_command_sections import (
    EDUCATIONAL_MATERIAL_LABELS,
)
from nutrition_charting.data.questionnaires import QUESTIONNAIRE_SECTIONS
from nutrition_charting.data.single_command_sections import (
    RECOMMENDED_LAB_LABELS,
)


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _age_in_years(birth_date: date | None) -> int | None:
    """Plain-stdlib age computation — avoids pulling arrow into a sandbox-
    sensitive module just for one field."""
    if birth_date is None:
        return None
    today = date.today()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years = years - 1
    return years if years >= 0 else None


def _patient_block(patient_id: str) -> dict[str, Any]:
    """Demographics for the print header. Returns blanks if the patient
    isn't found — print should still render even on a stale note context."""
    if not patient_id:
        return {}
    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        log.warning(f"[print_payload] patient {patient_id} not found")
        return {}

    full_name = " ".join(
        n for n in (patient.first_name, patient.last_name) if n
    ).strip()
    return {
        "full_name": full_name,
        "birth_date": _safe_str(patient.birth_date),
        "age": _age_in_years(patient.birth_date),
        "sex_at_birth": _safe_str(patient.sex_at_birth),
        "mrn": _safe_str(getattr(patient, "mrn", "")),
    }


def _note_block(note_uuid: str) -> dict[str, Any]:
    """Visit metadata + provider info pulled from the Note + its provider Staff."""
    if not note_uuid:
        return {}
    try:
        note = Note.objects.select_related("note_type_version", "provider").get(
            id=note_uuid,
        )
    except Note.DoesNotExist:
        log.warning(f"[print_payload] note {note_uuid} not found")
        return {}

    provider = note.provider
    provider_name = ""
    provider_npi = ""
    if provider is not None:
        provider_name = " ".join(
            n for n in (provider.first_name, provider.last_name) if n
        ).strip()
        provider_npi = _safe_str(getattr(provider, "npi_number", ""))

    note_type_name = ""
    if note.note_type_version is not None:
        note_type_name = _safe_str(note.note_type_version.name)

    return {
        "note_type_name": note_type_name,
        "datetime_of_service": _safe_str(note.datetime_of_service),
        "provider_name": provider_name,
        "provider_npi": provider_npi,
    }


def _questionnaire_section(
    section_id: str, sections: dict[str, Any],
) -> list[dict[str, str]]:
    """Resolve a saved questionnaire-section payload into [(label, text)] rows
    suitable for the template. Empty answers are dropped."""
    config = QUESTIONNAIRE_SECTIONS.get(section_id)
    if not config:
        return []
    saved = sections.get(section_id) or {}
    if not isinstance(saved, dict):
        return []
    rows: list[dict[str, str]] = []
    for field_id, label in config["fields"]:
        text = _safe_str(saved.get(field_id))
        if text:
            rows.append({"label": label, "text": text})
    return rows


def _flat_field(sections: dict[str, Any], section_id: str, field_id: str) -> str:
    saved = sections.get(section_id) or {}
    if not isinstance(saved, dict):
        return ""
    return _safe_str(saved.get(field_id))


def _multi_rows(
    sections: dict[str, Any], section_id: str, value_field: str,
) -> list[str]:
    """Flatten a multi-command section's saved rows to a list of value strings."""
    saved = sections.get(section_id) or {}
    if not isinstance(saved, dict):
        return []
    rows = saved.get("rows")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _safe_str(row.get(value_field))
        if text:
            out.append(text)
    return out


def _recommended_labs(sections: dict[str, Any]) -> list[str]:
    """Turn the canonical checklist + 'other' free-text into a single bulleted
    list of human labels (matching what the saved Plan command's narrative
    looks like)."""
    saved = sections.get("recommended_labs") or {}
    if not isinstance(saved, dict):
        return []

    items: list[str] = []
    selected = saved.get("selected")
    if isinstance(selected, list):
        for key in selected:
            if isinstance(key, str) and key.strip():
                items.append(RECOMMENDED_LAB_LABELS.get(key, key))
    elif isinstance(selected, str):
        # Tolerate a newline-separated paste, same as the save-side builder.
        for line in selected.splitlines():
            label = line.strip()
            if label:
                items.append(RECOMMENDED_LAB_LABELS.get(label, label))

    other = saved.get("other")
    if isinstance(other, str):
        items.extend(line.strip() for line in other.splitlines() if line.strip())
    elif isinstance(other, list):
        items.extend(_safe_str(x) for x in other if _safe_str(x))
    return items


def _educational_materials(sections: dict[str, Any]) -> list[str]:
    """Each saved row's `name` value — canonical names round-trip through
    EDUCATIONAL_MATERIAL_LABELS so the print uses the same human label the
    dietician saw on the form."""
    saved = sections.get("educational_materials") or {}
    if not isinstance(saved, dict):
        return []
    rows = saved.get("rows")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _safe_str(row.get("name"))
        if not name:
            continue
        # If the row_id encodes a canonical key, prefer the label map so any
        # future label change is reflected without requiring a resave.
        row_id = _safe_str(row.get("row_id"))
        if row_id.startswith("material:"):
            canonical_key = row_id.split(":", 1)[1]
            name = EDUCATIONAL_MATERIAL_LABELS.get(canonical_key, name)
        out.append(name)
    return out


def _monitor_team_meeting(sections: dict[str, Any]) -> dict[str, Any]:
    saved = sections.get("monitor_team_meeting") or {}
    if not isinstance(saved, dict):
        return {"checked": False, "comment": ""}
    monitor = saved.get("monitor")
    checked = monitor in (True, "true", "on", "1", 1, "yes")
    return {"checked": checked, "comment": _safe_str(saved.get("comment"))}


def _safe_chart_review(
    patient_id: str, *, cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not patient_id:
        return {"missing": True}
    try:
        return build_chart_review(patient_id, cache=cache)
    except Exception as exc:
        log.error(f"[print_payload] chart review failed: {exc!r}")
        return {"missing": True, "error": str(exc)}


def build_print_payload(note_uuid: str, patient_id: str) -> dict[str, Any]:
    """Assemble the full structured payload for the print template.

    The shape is stable and JSON-serializable so the renderer (and tests) can
    rely on every field being present even when sections are unsaved — empty
    strings, empty lists, or `None` instead of missing keys.
    """
    state = get_form_state(note_uuid) if note_uuid else {"sections": {}, "visit_type": ""}
    sections = state.get("sections") or {}
    visit_type = _safe_str(state.get("visit_type")) or "initial"

    cache: dict[str, Any] = {}
    chart = _safe_chart_review(patient_id, cache=cache)

    return {
        "patient": _patient_block(patient_id),
        "note": _note_block(note_uuid),
        "visit_type": visit_type,
        "chart": chart,
        "anthropometrics": _anthropometrics(sections, chart),
        "questionnaires": {
            "social_diet_history": _questionnaire_section("social_diet_history", sections),
            "dietary_intake": _questionnaire_section("dietary_intake", sections),
            "nfpe": _questionnaire_section("nfpe", sections),
            "nutrition_diagnosis_pes": _questionnaire_section(
                "nutrition_diagnosis_pes", sections,
            ),
        },
        "estimated_requirements": {
            "calories": _flat_field(sections, "estimated_nutrition_requirements", "calories"),
            "protein": _flat_field(sections, "estimated_nutrition_requirements", "protein"),
            "carbohydrates": _flat_field(
                sections, "estimated_nutrition_requirements", "carbohydrates",
            ),
            "fluid": _flat_field(sections, "estimated_nutrition_requirements", "fluid"),
        },
        "intervention": {
            "educational_materials": _educational_materials(sections),
            "counseling_narrative": _flat_field(
                sections, "counseling_narrative", "counseling_narrative",
            ),
        },
        "monitoring": {
            "goals": _multi_rows(sections, "goals", "goal_statement"),
            "follow_up_date": _flat_field(
                sections, "follow_up_appointment", "follow_up_date",
            ),
            "follow_up_comment": _flat_field(
                sections, "follow_up_appointment", "follow_up_comment",
            ),
        },
        "coordination": {
            "referrals": _multi_rows(sections, "referrals", "notes_to_specialist"),
            "recommended_labs": _recommended_labs(sections),
            "recommended_supplementation": _flat_field(
                sections, "recommended_supplementation", "supplementation",
            ),
            "monitor_team_meeting": _monitor_team_meeting(sections),
        },
    }


def _anthropometrics(
    sections: dict[str, Any], chart: dict[str, Any],
) -> dict[str, Any]:
    """Combine the dietician's saved overrides (UBW/IBW + height/weight) with
    the latest chart values as a fallback. Saved values win when both exist."""
    saved = sections.get("medical_chart_review") or {}
    if not isinstance(saved, dict):
        saved = {}
    chart_anthro = chart.get("anthropometrics") if isinstance(chart, dict) else {}
    chart_anthro = chart_anthro if isinstance(chart_anthro, dict) else {}
    return {
        "height": _safe_str(saved.get("height")) or _safe_str(chart_anthro.get("height")),
        "weight": _safe_str(saved.get("weight")) or _safe_str(chart_anthro.get("weight")),
        "bmi": _safe_str(saved.get("bmi")),
        "ubw": _safe_str(saved.get("ubw")),
        "ibw": _safe_str(saved.get("ibw")),
    }
