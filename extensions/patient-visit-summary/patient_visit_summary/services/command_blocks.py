"""Reusable block-builder for rendering Canvas note command data.

This module turns raw note command data (from `NoteDataExtractor`) into a list
of structured display "blocks" — simple dicts consumed by the
`templates/command_block.html` template. Any plugin that needs to render note
commands in a print/report UI can import `build_blocks`, `title_for_entry`, and
`render_blocks_html`.

Each render type lives in its own small function, and the public entry points
dispatch through the `BLOCK_BUILDERS` / `TITLE_EXTRACTORS` registries. Adding a
new render type is:

    1. Write `_blocks_<type>(display_name, data) -> list[dict]`
    2. Optionally write `_title_<type>(entry) -> str`
    3. Register both in the registries at the bottom of this file.

Block shape (understood by `templates/command_block.html`):

    {"kind": "heading",       "prefix": str, "value": str}
    {"kind": "heading_plain", "value": str}
    {"kind": "subheading",    "prefix": str, "value": str, "ts": str|None}
    {"kind": "field",         "label": str, "value": str}
    {"kind": "subfield",      "label": str, "value": str}   # indented
    {"kind": "field_block",   "label": str, "value": str}   # label on top
    {"kind": "body",          "value": str}
    {"kind": "vitals",        "items": [{"label": str, "value": str}, ...]}
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from canvas_sdk.templates import render_to_string

from patient_visit_summary.services.code_utils import coded_title
from patient_visit_summary.services.note_data_extractor import format_icd10_code


# ---- Field metadata ---------------------------------------------------------

INTERNAL_FIELD_PREFIXES: tuple[str, ...] = ("_", "skip-")
INTERNAL_FIELD_NAMES: set[str] = {
    "id", "pk", "coding", "entered_in_error", "state", "schema_key", "external_id",
}

# Keys whose pretty label differs from `KEY.upper().replace("_", " ")`.
FIELD_LABEL_OVERRIDES: dict[str, str] = {
    "today_assessment": "TODAY'S ASSESSMENT",
    "todays_assessment": "TODAY'S ASSESSMENT",
    "approximate_date_of_onset": "APPROXIMATE DATE OF ONSET",
    "notes_to_specialist": "NOTES TO SPECIALIST",
    "notes_to_pharmacist": "NOTES TO PHARMACIST",
}

REVIEW_TITLE_KEYS: tuple[str, ...] = (
    "report", "reports", "documents", "linked_items", "reviewed_documents",
    "lab_report", "imaging_report", "consult_report", "document",
)
REVIEW_HEADING_KEYS: set[str] = {"report"}

MEDICATION_TITLE_KEYS: tuple[str, ...] = (
    "change_medication_to", "new_medication", "new_prescription",
    "prescribe", "fdbMedId", "medication", "current_medication",
)
MEDICATION_HEADING_KEYS: set[str] = set(MEDICATION_TITLE_KEYS)

IMMUNIZE_TITLE_KEYS: tuple[str, ...] = ("coding", "immunization", "vaccine", "cvx", "cpt")
IMMUNIZATION_STATEMENT_TITLE_KEYS: tuple[str, ...] = (
    "statement", "immunization", "vaccine", "coding", "cvx", "cpt",
)
FAMILY_HISTORY_TITLE_KEYS: tuple[str, ...] = ("family_history", "condition", "fh")


# ---- Primitive helpers ------------------------------------------------------

def value_to_text(val: Any) -> str:
    """Render any value as a short display string, or '' when empty/unrenderable."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, datetime):
        return val.date().isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, dict):
        # Approximate-date shape: {"input": "last year", "date": "2025-04-24"}
        if "input" in val or "date" in val:
            input_text = str(val.get("input") or "").strip()
            date_text = str(val.get("date") or "").strip()
            if input_text and date_text and input_text != date_text:
                return f"{input_text} (around {date_text})"
            return input_text or date_text
        for key in ("text", "display", "name", "label", "value"):
            v = val.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    if isinstance(val, list):
        parts = [t for t in (value_to_text(item) for item in val) if t]
        return ", ".join(parts)
    return ""


def format_field_label(key: str) -> str:
    if key in FIELD_LABEL_OVERRIDES:
        return FIELD_LABEL_OVERRIDES[key]
    return key.replace("_", " ").upper()


def first_text_from_keys(entry: dict, keys: tuple[str, ...]) -> str:
    """First non-empty `value_to_text` of `entry[k]` for k in keys."""
    for key in keys:
        if key in entry:
            title = value_to_text(entry[key])
            if title:
                return title
    return ""


def medication_title(entry: dict) -> str:
    return first_text_from_keys(entry, MEDICATION_TITLE_KEYS)


def immunize_title(entry: dict) -> str:
    return first_text_from_keys(entry, IMMUNIZE_TITLE_KEYS)


def review_title(entry: dict) -> str:
    return first_text_from_keys(entry, REVIEW_TITLE_KEYS)


def condition_text(val: Any) -> str:
    """'<text> (<ICD10>)' for a condition/diagnose dict, text-only if no code."""
    if not isinstance(val, dict):
        return value_to_text(val)
    text = (val.get("text") or val.get("display") or "").strip()
    annotations = val.get("annotations") or []
    icd10_raw = val.get("value")
    icd10 = ""
    if annotations:
        first = annotations[0]
        if isinstance(first, str) and first.strip():
            icd10 = first.strip()
    if not icd10 and isinstance(icd10_raw, str) and icd10_raw.strip():
        icd10 = icd10_raw.strip()
    if icd10:
        icd10_formatted = icd10 if "." in icd10 else format_icd10_code(icd10)
    else:
        icd10_formatted = ""
    if text and icd10_formatted:
        return f"{text} ({icd10_formatted})"
    return text or icd10_formatted or ""


def strip_trailing_parens(text: str) -> str:
    """Drop a trailing `(...)` annotation (e.g. "Sage (allergy group)" → "Sage")."""
    if not isinstance(text, str):
        return text or ""
    stripped = text.rstrip()
    if stripped.endswith(")") and " (" in stripped:
        return stripped[: stripped.rfind(" (")].rstrip()
    return stripped


def truncate(text: Any, limit: int = 60) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def extra_blocks(entry: Any, shown_keys: set[str]) -> list[dict]:
    """Field blocks for all non-empty fields of an entry not in shown_keys."""
    if not isinstance(entry, dict):
        return []
    out: list[dict] = []
    for key, val in entry.items():
        if key in shown_keys or key in INTERNAL_FIELD_NAMES:
            continue
        if any(key.startswith(p) for p in INTERNAL_FIELD_PREFIXES):
            continue
        text = value_to_text(val)
        if not text:
            continue
        out.append({"kind": "field", "label": format_field_label(key), "value": text})
    return out


def compute_bmi(vitals: dict) -> str:
    """BMI as 'XX.X' when height + weight are both present, else ''.

    BMI = (weight_lbs + weight_oz/16) / height_in^2 * 703
    """
    try:
        height = float(vitals.get("height") or 0)
        lbs = float(vitals.get("weight_lbs") or 0)
        ozs = float(vitals.get("weight_oz") or 0)
    except (TypeError, ValueError):
        return ""
    if height <= 0 or lbs <= 0:
        return ""
    total_lbs = lbs + (ozs / 16.0)
    bmi = (total_lbs / (height * height)) * 703.0
    return f"{bmi:.1f}"


# ---- Tiny block constructors (keep renderers readable) ----------------------

def _heading(prefix: str, value: str) -> dict:
    return {"kind": "heading", "prefix": prefix, "value": value}


def _heading_plain(value: str) -> dict:
    return {"kind": "heading_plain", "value": value}


def _subheading(prefix: str, value: str, ts: str = "") -> dict:
    return {"kind": "subheading", "prefix": prefix, "value": value, "ts": ts}


def _field(label: str, value: str) -> dict:
    return {"kind": "field", "label": label, "value": value}


def _subfield(label: str, value: str) -> dict:
    return {"kind": "subfield", "label": label, "value": value}


def _body(value: str) -> dict:
    return {"kind": "body", "value": value}


def _heading_or_plain(prefix: str, title: str) -> dict:
    """Heading with the prefix and title, or a plain heading when title is empty."""
    return _heading(prefix, title) if title else _heading_plain(prefix)


def _joined_list_field(label: str, items: list, key: str = "text") -> dict | None:
    """Comma-join `item[key]` across a list of dicts; return field block or None."""
    if not isinstance(items, list) or not items:
        return None
    texts = [i.get(key, "") for i in items if isinstance(i, dict) and i.get(key)]
    return _field(label, ", ".join(texts)) if texts else None


def _indications_field(items: list) -> dict | None:
    """Comma-join `condition_text` across an indications list."""
    if not isinstance(items, list) or not items:
        return None
    texts = [t for t in (condition_text(i) for i in items) if t]
    return _field("INDICATIONS", ", ".join(texts)) if texts else None


# ---- Per-render-type block builders ----------------------------------------
#
# Each builder has signature: (display_name: str, data: Any) -> list[dict]

def _blocks_rfv(display_name: str, data: Any) -> list[dict]:
    """RFV: heading per command; COMMENT subfield when present."""
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for entry in data:
        if isinstance(entry, dict):
            text = entry.get("text", "")
            comment = entry.get("comment", "")
        else:
            text = value_to_text(entry)
            comment = ""
        if not text and not comment:
            continue
        out.append(_heading(display_name, text))
        if comment:
            out.append(_field("COMMENT", comment))
    return out


def _blocks_hpi(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = [_heading_plain(display_name)]
    for item in data:
        narrative = item.get("narrative", "") if isinstance(item, dict) else str(item)
        if narrative:
            out.append(_body(narrative))
        if isinstance(item, dict):
            out.extend(extra_blocks(item, shown_keys={"narrative"}))
    return out


def _blocks_ros_or_exam(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for ros in data:
        name = ros.get("questionnaire", "") if isinstance(ros, dict) else str(ros)
        out.append(_subheading(display_name, name))
        for qa in (ros.get("questions_and_answers", []) if isinstance(ros, dict) else []):
            out.append(_subfield(qa.get("label", ""), qa.get("answer", "")))
    return out


def _blocks_questionnaire(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for q in data:
        out.append(_subheading(display_name, q.get("name", ""), ts=q.get("last_updated", "")))
        if result := q.get("result"):
            out.append(_field("RESULT", str(result)))
        for qa in q.get("questions_and_answers", []):
            out.append(_field(qa.get("label", "").upper(), qa.get("answer", "")))
    return out


_VITALS_FIELD_MAP: list[tuple[str, str, str | None]] = [
    ("height", "HEIGHT", "in"),
    ("weight_lbs", "WEIGHT", "lb"),
    ("waist_circumference", "WAIST CIRCUMFERENCE", "cm"),
    ("body_temperature", "TEMPERATURE", "°F"),
    ("body_temperature_site", "SITE", None),
    ("blood_pressure_systole", "BLOOD PRESSURE", None),
    ("blood_pressure_position_and_site", "POSITION AND SITE", None),
    ("pulse", "PULSE RATE", "bpm"),
    ("pulse_rhythm", "PULSE RHYTHM", None),
    ("respiration_rate", "RESPIRATION RATE", "bpm"),
    ("oxygen_saturation", "OXYGEN SATURATION", "%"),
    ("note", "NOTE", None),
]


def _format_vitals_value(vitals: dict, key: str, val: Any, unit: str | None, bmi: str) -> str:
    if key == "blood_pressure_systole":
        diastole = vitals.get("blood_pressure_diastole", "")
        return f"{val}/{diastole} mmHg" if diastole or diastole == 0 else f"{val} mmHg"
    if key == "weight_lbs":
        ozs = vitals.get("weight_oz")
        display = f"{val} lb {ozs} oz" if ozs or ozs == 0 else f"{val} lb"
        return display + (f" (BMI: {bmi})" if bmi else "")
    if unit:
        return f"{val} {unit}"
    return str(val)


def _blocks_vitals(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for vitals in data:
        # bmi is derived/rendered inline below; weight_oz is folded into the
        # weight line. Both are suppressed so extra_blocks doesn't re-emit them.
        shown = {"blood_pressure_diastole", "weight_oz", "bmi"}
        bmi = compute_bmi(vitals)
        items: list[dict] = []
        for key, label, unit in _VITALS_FIELD_MAP:
            shown.add(key)
            val = vitals.get(key)
            if not val and val != 0:
                continue
            items.append({"label": label, "value": _format_vitals_value(vitals, key, val, unit, bmi)})
        out.append(_heading_plain("Vitals"))
        if items:
            out.append({"kind": "vitals", "items": items})
        out.extend(extra_blocks(vitals, shown_keys=shown))
    return out


def _blocks_assess(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for a in data:
        out.append(_heading("Assessment", condition_text(a.get("condition", {}))))
        if bg := a.get("background"):
            out.append(_field("BACKGROUND", bg))
        if status := a.get("status"):
            out.append(_field("STATUS", str(status)))
        if narrative := a.get("narrative"):
            out.append(_field("TODAY'S ASSESSMENT", narrative))
        out.extend(extra_blocks(a, shown_keys={"condition", "status", "narrative", "background"}))
    return out


def _blocks_diagnose(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for d in data:
        cmd_data = d.get("data", d)
        out.append(_heading("Diagnose", condition_text(cmd_data.get("diagnose", {}))))
        if bg := cmd_data.get("background"):
            out.append(_field("BACKGROUND", bg))
        out.extend(extra_blocks(cmd_data, shown_keys={"diagnose", "background"}))
    return out


def _blocks_change_diagnosis(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        cmd_data = entry.get("data", entry) if isinstance(entry, dict) else {}
        out.append(_heading("Change Diagnosis", condition_text(cmd_data.get("condition", {}))))
        if new_text := condition_text(cmd_data.get("new_condition", {})):
            out.append(_field("NEW DIAGNOSIS", new_text))
        if bg := cmd_data.get("background"):
            out.append(_field("BACKGROUND", bg))
        if narrative := cmd_data.get("narrative"):
            out.append(_field("TODAY'S ASSESSMENT", narrative))
        out.extend(extra_blocks(
            cmd_data, shown_keys={"condition", "new_condition", "background", "narrative"},
        ))
    return out


def _blocks_resolve_condition(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        cmd_data = entry.get("data", entry) if isinstance(entry, dict) else {}
        out.append(_heading("Resolve Condition", condition_text(cmd_data.get("condition", {}))))
        if rationale := cmd_data.get("rationale"):
            out.append(_field("RATIONALE", rationale))
        out.extend(extra_blocks(cmd_data, shown_keys={"condition", "rationale"}))
    return out


def _blocks_plan(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = [_heading_plain("Plan")]
    for p in data:
        narrative = p.get("narrative", "") if isinstance(p, dict) else str(p)
        if narrative:
            out.append(_body(narrative))
        if isinstance(p, dict):
            out.extend(extra_blocks(p, shown_keys={"narrative"}))
    return out


def _med_action_row(entry: dict) -> dict | None:
    """Build the inline DAYS SUPPLY / QUANTITY TO DISPENSE / REFILLS row."""
    items: list[dict] = []
    days_supply = entry.get("days_supply")
    if days_supply or days_supply == 0:
        items.append({"label": "DAYS SUPPLY", "value": str(days_supply)})
    qty = entry.get("quantity_to_dispense")
    type_to_dispense = entry.get("type_to_dispense")
    qty_type_text = type_to_dispense.get("text", "") if isinstance(type_to_dispense, dict) else ""
    if qty or qty == 0:
        qty_display = f"{qty} × {qty_type_text}" if qty_type_text else str(qty)
        items.append({"label": "QUANTITY TO DISPENSE", "value": qty_display})
    refills = entry.get("refills")
    if refills or refills == 0:
        items.append({"label": "REFILLS", "value": str(refills)})
    return {"kind": "vitals", "items": items} if items else None


def _blocks_med_action(display_name: str, data: Any) -> list[dict]:
    """Shared renderer for prescribe / refill / stop / adjust / change medication."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading_or_plain(display_name, medication_title(entry)))

        cm_to = entry.get("change_medication_to")
        if cm_to:
            cm_text = value_to_text(cm_to)
            prev_text = value_to_text(entry.get("prescribe"))
            if cm_text and prev_text and cm_text != prev_text:
                out.append(_field("CHANGE FROM", prev_text))

        if ind := _indications_field(entry.get("indications") or []):
            out.append(ind)
        if sig := entry.get("sig"):
            out.append(_field("SIG", str(sig)))
        if row := _med_action_row(entry):
            out.append(row)
        if subs := entry.get("substitutions"):
            out.append(_field("SUBSTITUTIONS ALLOWED", str(subs).capitalize()))
        if pharmacy := value_to_text(entry.get("pharmacy")):
            out.append(_field("PHARMACY", pharmacy))
        if prescriber := value_to_text(entry.get("prescriber")):
            out.append(_field("PRESCRIBER", prescriber))
        if sup := value_to_text(entry.get("supervising_provider")):
            out.append(_field("SUPERVISING PROVIDER", sup))
        if note := entry.get("note_to_pharmacist"):
            out.append(_field("NOTE TO PHARMACIST", str(note)))

        out.extend(extra_blocks(entry, shown_keys=set(MEDICATION_HEADING_KEYS) | {
            "indications", "sig", "days_supply", "quantity_to_dispense",
            "type_to_dispense", "refills", "substitutions", "pharmacy", "prescriber",
            "supervising_provider", "note_to_pharmacist",
        }))
    return out


def _blocks_refer(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        out.append(_heading("Referral", value_to_text(r.get("refer_to"))))
        if ind := _indications_field(r.get("indications") or []):
            out.append(ind)
        if cq := r.get("clinical_question"):
            out.append(_field("CLINICAL QUESTION", str(cq)))
        if priority := r.get("priority"):
            out.append(_field("PRIORITY", str(priority)))
        if notes := r.get("notes_to_specialist"):
            out.append(_field("NOTES TO SPECIALIST", notes))
        if "include_visit_note" in r and r["include_visit_note"] is not None:
            out.append(_field("INCLUDE VISIT NOTE", "Yes" if r["include_visit_note"] else "No"))
        if ic := r.get("internal_comment"):
            out.append(_field("INTERNAL COMMENT", ic))
        if docs := _joined_list_field("DOCUMENTS TO INCLUDE", r.get("documents_to_include") or []):
            out.append(docs)
        if linked := _joined_list_field("LINKED ITEMS", r.get("linked_items") or []):
            out.append(linked)
        out.extend(extra_blocks(r, shown_keys={
            "refer_to", "indications", "clinical_question", "priority",
            "notes_to_specialist", "include_visit_note", "internal_comment",
            "documents_to_include", "linked_items",
        }))
    return out


def _blocks_lab_order(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for lo in data:
        if not isinstance(lo, dict):
            continue
        out.append(_heading_or_plain("Lab Order", value_to_text(lo.get("lab_partner"))))

        tests = lo.get("tests") or []
        # AOE labels need a code→text lookup built from the tests list.
        test_by_code: dict[str, str] = {}
        if isinstance(tests, list):
            for t in tests:
                if isinstance(t, dict) and t.get("value") is not None and t.get("text"):
                    test_by_code[str(t["value"])] = t["text"]

        if tests_field := _joined_list_field("TESTS", tests):
            out.append(tests_field)
        if op_text := value_to_text(lo.get("ordering_provider")):
            out.append(_field("ORDERING PROVIDER", op_text))
        if ind := _indications_field(lo.get("diagnosis") or []):
            ind["label"] = "INDICATIONS"
            out.append(ind)
        if "fasting_status" in lo and lo["fasting_status"] is not None:
            out.append(_field("FASTING REQUIRED", "Yes" if lo["fasting_status"] else "No"))

        aoe_keys_shown: set[str] = set()
        for key, val in lo.items():
            if not key.startswith("aoes|"):
                continue
            aoe_keys_shown.add(key)
            text_val = value_to_text(val)
            if not text_val:
                continue
            test_code = key.split("|")[1] if "|" in key else ""
            test_text = test_by_code.get(test_code, "")
            label = f"({test_text.upper()}) NEW QUESTION" if test_text else "NEW QUESTION"
            out.append(_field(label, text_val))

        if comment := lo.get("comment"):
            out.append(_field("COMMENT", comment))
        out.extend(extra_blocks(lo, shown_keys={
            "lab_partner", "tests", "ordering_provider", "diagnosis",
            "fasting_status", "comment",
        } | aoe_keys_shown))
    return out


def _blocks_imaging_order(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for io in data:
        if not isinstance(io, dict):
            continue
        out.append(_heading("Image", value_to_text(io.get("image"))))
        if ind := _indications_field(io.get("indications") or []):
            out.append(ind)
        if priority := io.get("priority"):
            out.append(_field("PRIORITY", str(priority)))
        if add_details := io.get("additional_details"):
            out.append(_field("ADDITIONAL ORDER DETAILS", add_details))
        if ic_text := value_to_text(io.get("imaging_center")):
            out.append(_field("IMAGING CENTER", ic_text))
        if op_text := value_to_text(io.get("ordering_provider")):
            out.append(_field("ORDERING PROVIDER", op_text))
        if comment := io.get("comment"):
            out.append(_field("INTERNAL COMMENT", comment))
        if linked := _joined_list_field("LINKED ITEMS", io.get("linked_items") or []):
            out.append(linked)
        out.extend(extra_blocks(io, shown_keys={
            "image", "indications", "priority", "additional_details",
            "imaging_center", "ordering_provider", "comment", "linked_items",
        }))
    return out


def _blocks_review(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading(display_name, review_title(entry)))
        if msg := entry.get("message_to_patient"):
            out.append(_field("PATIENT MESSAGE", str(msg)))
        if comm := value_to_text(entry.get("communication_method")):
            out.append(_field("PATIENT COMMUNICATION", comm))
        if linked := _joined_list_field("LINKED ITEMS", entry.get("linked_items") or []):
            out.append(linked)
        if ic := entry.get("internal_comment"):
            out.append(_field("INTERNAL COMMENT", str(ic)))
        out.extend(extra_blocks(entry, shown_keys=REVIEW_HEADING_KEYS | {
            "message_to_patient", "communication_method", "linked_items", "internal_comment",
        }))
    return out


def _blocks_medication_statement(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = value_to_text(entry.get("medication") or entry.get("fdbMedId"))
        out.append(_heading_or_plain("Medication Statement", name))
        if sig := entry.get("sig"):
            out.append(_field("SIG", str(sig)))
        out.extend(extra_blocks(entry, shown_keys={"medication", "fdbMedId", "sig"}))
    return out


def _blocks_remove_allergy(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading_or_plain("Remove Allergy", value_to_text(entry.get("allergy"))))
        if rationale := (entry.get("narrative") or entry.get("rationale")):
            out.append(_field("RATIONALE", str(rationale)))
        out.extend(extra_blocks(entry, shown_keys={"allergy", "narrative", "rationale"}))
    return out


def _family_history_name(entry: dict) -> str:
    for k in FAMILY_HISTORY_TITLE_KEYS:
        if k not in entry:
            continue
        val = entry[k]
        text = condition_text(val) if isinstance(val, dict) else value_to_text(val)
        if text:
            return text
    return ""


def _blocks_family_history(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading_or_plain("Family History", _family_history_name(entry)))
        if relative := value_to_text(entry.get("relative")):
            out.append(_field("RELATIVE", relative))
        if note := entry.get("note"):
            out.append(_field("NOTE", str(note)))
        out.extend(extra_blocks(entry, shown_keys={
            "family_history", "condition", "fh", "relative", "note",
        }))
    return out


def _blocks_immunization_statement(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = coded_title(
            first_text_from_keys(entry, IMMUNIZATION_STATEMENT_TITLE_KEYS),
            entry.get("statement"),
        )
        out.append(_heading_or_plain("Immunization Statement", name))
        if date_val := (entry.get("approximate_date") or entry.get("date")):
            out.append(_field(
                "APPROXIMATE DATE OF IMMUNIZATION",
                value_to_text(date_val) or str(date_val),
            ))
        if comment_val := (entry.get("comments") or entry.get("comment")):
            out.append(_field("COMMENT", comment_val))
        out.extend(extra_blocks(entry, shown_keys={
            "statement", "immunization", "vaccine", "coding", "cvx", "cpt",
            "approximate_date", "date", "comments", "comment",
        }))
    return out


def _blocks_surgical_history(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        psh = entry.get("past_surgical_history")
        name = condition_text(psh) if isinstance(psh, dict) else value_to_text(psh)
        out.append(_heading_or_plain("Past Surgical History", name))
        if approx := entry.get("approximate_date"):
            out.append(_field("APPROXIMATE DATE", value_to_text(approx) or str(approx)))
        if comment := entry.get("comment"):
            out.append(_field("COMMENT", comment))
        out.extend(extra_blocks(entry, shown_keys={
            "past_surgical_history", "approximate_date", "comment",
        }))
    return out


def _blocks_medical_history(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        pmh = entry.get("past_medical_history")
        name = condition_text(pmh) if isinstance(pmh, dict) else value_to_text(pmh)
        out.append(_heading_or_plain("Past Medical History", name))
        if start := entry.get("approximate_start_date"):
            out.append(_field("APPROXIMATE START DATE", value_to_text(start) or str(start)))
        if end := entry.get("approximate_end_date"):
            out.append(_field("APPROXIMATE END DATE", value_to_text(end) or str(end)))
        if "show_on_condition_list" in entry and entry["show_on_condition_list"] is not None:
            out.append(_field(
                "SHOW ON CONDITION LIST",
                "Yes" if entry["show_on_condition_list"] else "No",
            ))
        if comments := entry.get("comments"):
            out.append(_field("COMMENTS", comments))
        out.extend(extra_blocks(entry, shown_keys={
            "past_medical_history", "approximate_start_date", "approximate_end_date",
            "show_on_condition_list", "comments",
        }))
    return out


def _blocks_perform(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading_or_plain(
            "Perform", coded_title(value_to_text(entry.get("perform")), entry.get("perform")),
        ))
        if notes := entry.get("notes"):
            out.append(_field("NOTES", str(notes)))
        out.extend(extra_blocks(entry, shown_keys={"perform", "notes"}))
    return out


def _blocks_immunize(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading_or_plain(
            "Immunize", coded_title(immunize_title(entry), entry.get("coding")),
        ))
        if lot := entry.get("lot_number"):
            out.append(_field("LOT NUMBER", str(lot)))
        if mfr := entry.get("manufacturer"):
            out.append(_field("MANUFACTURER", value_to_text(mfr) or str(mfr)))
        if exp_val := (entry.get("expiration_date") or entry.get("exp_date_original")):
            out.append(_field("EXPIRATION DATE", value_to_text(exp_val) or str(exp_val)))
        if sig_val := (entry.get("sig") or entry.get("sig_original")):
            out.append(_field("SIG", str(sig_val)))
        consent = entry.get("vis_consent")
        if consent is None:
            consent = entry.get("consent_given")
        if consent is not None:
            consent_text = (
                ("Yes" if consent else "No") if isinstance(consent, bool) else str(consent)
            )
            out.append(_field("VIS CONSENT", consent_text))
        if given := value_to_text(entry.get("given_by")):
            out.append(_field("GIVEN BY", given))
        out.extend(extra_blocks(entry, shown_keys={
            "coding", "immunization", "vaccine", "cvx", "cpt",
            "lot_number", "manufacturer", "expiration_date", "exp_date_original",
            "sig", "sig_original", "vis_consent", "consent_given", "given_by",
        }))
    return out


def _billing_title(item: dict) -> str:
    """'Description (CPT)' for a billed-services row, falling back to either part."""
    code = str(item.get("code") or "").strip()
    description = str(item.get("description") or "").strip()
    if description and code:
        return f"{description} ({code})"
    return description or code


def _blocks_billing(display_name: str, data: Any) -> list[dict]:
    """Patient-facing billed services: CPT (+ modifiers) and description, with units.

    No charge amounts — this is a patient handout, not a superbill.
    """
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = _billing_title(item)
        if not title:
            continue
        out.append(_heading_or_plain(display_name, title))
        units = item.get("units")
        if units not in (None, ""):
            out.append(_field("UNITS", str(units)))
    return out


def _blocks_task(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for t in data:
        if not isinstance(t, dict):
            continue
        out.append(_heading("Task", str(t.get("title", ""))))
        if assign := value_to_text(t.get("assign_to")):
            out.append(_field("ASSIGN TO", assign))
        if due := t.get("due_date"):
            out.append(_field("DUE DATE", value_to_text(due) or str(due)))
        if comment := t.get("comment"):
            out.append(_field("COMMENT", comment))
        labels = t.get("labels") or []
        if isinstance(labels, list) and labels:
            label_texts = [x for x in (value_to_text(lbl) for lbl in labels) if x]
            if label_texts:
                out.append(_field("LABELS", ", ".join(label_texts)))
        if linked := _joined_list_field("LINKED ITEMS", t.get("linked_items") or []):
            out.append(linked)
        out.extend(extra_blocks(t, shown_keys={
            "title", "assign_to", "due_date", "comment", "labels", "linked_items",
        }))
    return out


def _blocks_instruct(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading("Instruct", value_to_text(entry.get("instruct"))))
        if narrative := entry.get("narrative"):
            out.append(_field("NARRATIVE", narrative))
        out.extend(extra_blocks(entry, shown_keys={"instruct", "narrative"}))
    return out


def _blocks_goal(display_name: str, data: Any) -> list[dict]:
    """Handles both Goal (goal_statement as str) and Update Goal (as dict)."""
    out: list[dict] = []
    for g in data:
        if not isinstance(g, dict):
            continue
        title = value_to_text(g.get("goal_statement")) or value_to_text(g.get("description"))
        prefix = "Update Goal" if isinstance(g.get("goal_statement"), dict) else "Goal"
        out.append(_heading_or_plain(prefix, title))
        if start := g.get("start_date"):
            out.append(_field("START DATE", str(start)))
        if due := g.get("due_date"):
            out.append(_field("DUE DATE", str(due)))
        if status := g.get("achievement_status"):
            out.append(_field("STATUS", str(status)))
        if priority := g.get("priority"):
            out.append(_field("PRIORITY", str(priority)))
        if progress := g.get("progress"):
            out.append(_field("PROGRESS / BARRIERS", progress))
        out.extend(extra_blocks(g, shown_keys={
            "goal_statement", "description", "start_date", "due_date",
            "achievement_status", "priority", "progress",
        }))
    return out


def _blocks_allergy(display_name: str, data: Any) -> list[dict]:
    out: list[dict] = []
    for a in data:
        name = strip_trailing_parens(value_to_text(a.get("allergy")))
        out.append(_heading("Allergy", name))
        out.extend(extra_blocks(a, shown_keys={"allergy"}))
    return out


def _blocks_generic(display_name: str, data: Any) -> list[dict]:
    """Fallback for render_types with no dedicated builder: heading + field dump."""
    if not isinstance(data, list):
        return []
    out: list[dict] = [_heading_plain(display_name)]
    for item in data:
        if isinstance(item, dict):
            out.extend(extra_blocks(item, shown_keys=set()))
        else:
            text = value_to_text(item)
            if text:
                out.append(_body(text))
    return out


# ---- Per-type sidebar title extractors --------------------------------------
#
# Each extractor has signature: (entry: dict) -> str (pre-truncation).

def _title_goal(entry: dict) -> str:
    return value_to_text(entry.get("goal_statement")) or value_to_text(entry.get("description"))


def _title_family_history(entry: dict) -> str:
    for k in FAMILY_HISTORY_TITLE_KEYS:
        if k in entry:
            val = entry[k]
            text = condition_text(val) if isinstance(val, dict) else value_to_text(val)
            if text:
                return text
    return ""


def _title_generic(entry: dict) -> str:
    for key in ("text", "name", "display", "description", "title", "narrative"):
        val = entry.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict) and val.get("text"):
            return val["text"]
    for val in entry.values():
        if isinstance(val, dict):
            text = val.get("text") or val.get("display") or val.get("name")
            if isinstance(text, str) and text.strip():
                return text
    return ""


# ---- Dispatch registries ---------------------------------------------------

BlockBuilder = Callable[[str, Any], list[dict]]
TitleExtractor = Callable[[dict], str]

BLOCK_BUILDERS: dict[str, BlockBuilder] = {
    "rfv": _blocks_rfv,
    "hpi": _blocks_hpi,
    "ros": _blocks_ros_or_exam,
    "exam": _blocks_ros_or_exam,
    "questionnaire": _blocks_questionnaire,
    "structured_assessment": _blocks_questionnaire,
    "vitals": _blocks_vitals,
    "assess": _blocks_assess,
    "diagnose": _blocks_diagnose,
    "change_diagnosis": _blocks_change_diagnosis,
    "resolve_condition": _blocks_resolve_condition,
    "plan": _blocks_plan,
    "med_action": _blocks_med_action,
    "prescribe": _blocks_med_action,  # alias for legacy callers
    "refer": _blocks_refer,
    "lab_order": _blocks_lab_order,
    "imaging_order": _blocks_imaging_order,
    "review": _blocks_review,
    "medication_statement": _blocks_medication_statement,
    "remove_allergy": _blocks_remove_allergy,
    "family_history": _blocks_family_history,
    "immunization_statement": _blocks_immunization_statement,
    "surgical_history": _blocks_surgical_history,
    "medical_history": _blocks_medical_history,
    "perform": _blocks_perform,
    "immunize": _blocks_immunize,
    "task": _blocks_task,
    "instruct": _blocks_instruct,
    "goal": _blocks_goal,
    "allergy": _blocks_allergy,
    "billing": _blocks_billing,
}


TITLE_EXTRACTORS: dict[str, TitleExtractor] = {
    "hpi": lambda e: e.get("narrative", ""),
    "plan": lambda e: e.get("narrative", ""),
    "ros": lambda e: e.get("questionnaire", ""),
    "exam": lambda e: e.get("questionnaire", ""),
    "questionnaire": lambda e: e.get("name", ""),
    "structured_assessment": lambda e: e.get("name", ""),
    "assess": lambda e: condition_text(e.get("condition")),
    "diagnose": lambda e: condition_text(e.get("data", e).get("diagnose")),
    "change_diagnosis": lambda e: condition_text(e.get("data", e).get("new_condition")),
    "resolve_condition": lambda e: condition_text(e.get("data", e).get("condition")),
    "review": review_title,
    "med_action": medication_title,
    "prescribe": medication_title,
    "refer": lambda e: value_to_text(e.get("refer_to")),
    "lab_order": lambda e: value_to_text(e.get("lab_partner")),
    "imaging_order": lambda e: value_to_text(e.get("image")),
    "task": lambda e: e.get("title", ""),
    "instruct": lambda e: value_to_text(e.get("instruct")),
    "goal": _title_goal,
    "allergy": lambda e: strip_trailing_parens(value_to_text(e.get("allergy"))),
    "immunize": immunize_title,
    "perform": lambda e: value_to_text(e.get("perform")),
    "medical_history": lambda e: condition_text(e.get("past_medical_history")),
    "surgical_history": lambda e: condition_text(e.get("past_surgical_history")),
    "immunization_statement": lambda e: first_text_from_keys(e, IMMUNIZATION_STATEMENT_TITLE_KEYS),
    "family_history": _title_family_history,
    "remove_allergy": lambda e: value_to_text(e.get("allergy")),
    "medication_statement": lambda e: value_to_text(e.get("medication") or e.get("fdbMedId")),
    "billing": _billing_title,
}


# ---- Section-level enumeration ---------------------------------------------
#
# `DEFAULT_SECTIONS` maps the raw template-context keys produced by
# `NoteDataExtractor.get_template_context()` to (display_name, render_type).
# `enumerate_sections()` walks this config, pulls each command out of the
# context, and pairs it with its rendered blocks + sidebar title — the
# single structured output every print UI can consume.

DEFAULT_SECTIONS: list[dict] = [
    {
        "key": "subjective",
        "title": "Subjective",
        "items": [
            ("reasons_for_visit", "Reason for Visit", "rfv"),
            ("history_of_present_illness_commands_data", "History of Present Illness", "hpi"),
            ("review_of_systems_data", "Review of Systems", "ros"),
            ("questionnaire_data", "Questionnaires", "questionnaire"),
        ],
    },
    {
        "key": "objective",
        "title": "Objective",
        "items": [
            ("vitals_commands_data", "Vitals", "vitals"),
            ("physical_exam_data", "Physical Exam", "exam"),
        ],
    },
    {
        "key": "assessment",
        "title": "Assessment",
        "items": [
            ("assessments_commands_data", "Assessments", "assess"),
            ("diagnose_commands_data", "Diagnoses", "diagnose"),
            ("structured_assessment_data", "Structured Assessments", "structured_assessment"),
            ("resolve_condition_commands_data", "Resolved Conditions", "resolve_condition"),
            ("change_diagnosis_commands_data", "Changed Diagnoses", "change_diagnosis"),
        ],
    },
    {
        "key": "reviews",
        "title": "Reviews",
        "items": [
            ("lab_reviews", "Lab Review", "review"),
            ("imaging_reviews", "Imaging Review", "review"),
            ("consult_report_reviews", "Consult Report Review", "review"),
            ("uncategorized_document_reviews", "Document Review", "review"),
        ],
    },
    {
        "key": "plan",
        "title": "Plan",
        "items": [
            ("plan_commands_data", "Plan", "plan"),
            ("prescribe_commands_data", "Prescribe", "med_action"),
            ("refill_commands_data", "Refill", "med_action"),
            ("stop_medication_commands_data", "Stop Medication", "med_action"),
            ("adjust_prescription_commands_data", "Adjust Prescription", "med_action"),
            ("change_medication_commands_data", "Change Medication", "med_action"),
            ("referral_commands_data", "Referrals", "refer"),
            ("lab_order_commands_data", "Lab Orders", "lab_order"),
            ("imaging_order_commands_data", "Imaging Orders", "imaging_order"),
            ("instruct_commands_data", "Instructions", "instruct"),
            ("task_commands_data", "Tasks", "task"),
            ("goal_commands_data", "Goals", "goal"),
            ("update_goal_commands_data", "Updated Goals", "goal"),
        ],
    },
    {
        "key": "procedures",
        "title": "Procedures",
        "items": [
            ("immunize_commands_data", "Immunize", "immunize"),
            ("perform_commands_data", "Procedures Performed", "perform"),
        ],
    },
    {
        "key": "history",
        "title": "History",
        "items": [
            ("allergy_commands_data", "Allergies", "allergy"),
            ("remove_allergy_commands_data", "Removed Allergies", "remove_allergy"),
            ("medication_statement_commands_data", "Medication Statements", "medication_statement"),
            ("immunization_statement_commands_data", "Immunization Statements", "immunization_statement"),
            ("patient_family_history_commands_data", "Family History", "family_history"),
            ("medical_history_commands_data", "Past Medical History", "medical_history"),
            ("surgical_history_commands_data", "Past Surgical History", "surgical_history"),
        ],
    },
    {
        "key": "billing",
        "title": "Billed Services",
        "items": [
            ("billing_line_items_data", "Billed Services", "billing"),
        ],
    },
]


def enumerate_sections(
    template_context: dict, sections: list[dict] | None = None,
) -> list[dict]:
    """Walk a sections config over a template context; return each present
    command grouped by section, with its sidebar title and rendered blocks.

    Output shape:
        [
            {
                "key": "plan",
                "title": "Plan",
                "groups": [
                    {
                        "context_key": "plan_commands_data",
                        "display_name": "Plan",
                        "render_type": "plan",
                        "entries": [
                            {"title": str, "blocks": list[dict], "raw": dict},
                            ...
                        ],
                    },
                    ...
                ],
            },
            ...
        ]

    Any section whose commands are all absent is omitted.
    """
    if sections is None:
        sections = DEFAULT_SECTIONS
    result: list[dict] = []
    for section_def in sections:
        groups: list[dict] = []
        for context_key, display_name, render_type in section_def["items"]:
            data = template_context.get(context_key)
            if not data:
                continue
            entries = data if isinstance(data, list) else [data]
            entries = [e for e in entries if e or e == 0]
            if not entries:
                continue
            per_entry = [
                {
                    "title": title_for_entry(render_type, display_name, entry, idx),
                    "blocks": build_blocks(display_name, render_type, [entry]),
                    "raw": entry,
                }
                for idx, entry in enumerate(entries)
            ]
            groups.append({
                "context_key": context_key,
                "display_name": display_name,
                "render_type": render_type,
                "entries": per_entry,
            })
        if groups:
            result.append({
                "key": section_def["key"],
                "title": section_def["title"],
                "groups": groups,
            })
    return result


def render_blocks(blocks: list[dict]) -> str:
    """Render an already-built list of blocks to HTML via the shared template."""
    if not blocks:
        return ""
    return render_to_string("templates/command_block.html", context={"blocks": blocks})


# ---- Public API -------------------------------------------------------------

def build_blocks(display_name: str, render_type: str, data: Any) -> list[dict]:
    """Convert a command data payload into a list of display blocks."""
    if not data:
        return []
    builder = BLOCK_BUILDERS.get(render_type)
    if builder is not None:
        return builder(display_name, data)
    return _blocks_generic(display_name, data)


def title_for_entry(render_type: str, display_name: str, entry: Any, idx: int) -> str:
    """Extract a short, human-readable sidebar title for a single command entry."""
    fallback = f"{display_name} #{idx + 1}"

    # `rfv` uses {text, comment} dicts OR bare strings.
    if render_type == "rfv":
        if isinstance(entry, dict):
            return truncate(entry.get("text", "") or entry.get("comment", "")) or fallback
        return truncate(str(entry)) or fallback

    if not isinstance(entry, dict):
        return truncate(str(entry)) or fallback

    if render_type == "vitals":
        return fallback

    extractor = TITLE_EXTRACTORS.get(render_type)
    if extractor is not None:
        return truncate(extractor(entry)) or fallback
    return truncate(_title_generic(entry)) or fallback


def render_blocks_html(display_name: str, render_type: str, data: Any) -> str:
    """Build blocks and render them to HTML via `templates/command_block.html`.
    Returns "" for empty data."""
    blocks = build_blocks(display_name, render_type, data)
    if not blocks:
        return ""
    return render_to_string("templates/command_block.html", context={"blocks": blocks})
