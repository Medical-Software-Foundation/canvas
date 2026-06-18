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

import re
from datetime import date, datetime
from typing import Any, Callable

from canvas_sdk.templates import render_to_string

from patient_visit_summary.services.code_utils import coded_title
from patient_visit_summary.services.note_data_extractor import format_icd10_code


# ---- Field metadata ---------------------------------------------------------

INTERNAL_FIELD_PREFIXES: tuple[str, ...] = ("_", "skip-")
INTERNAL_FIELD_NAMES: set[str] = {
    "id", "pk", "coding", "entered_in_error", "state", "schema_key", "external_id",
    # `coded_title` is the heading text computed by `_annotate_coded_titles`
    # in the extractor — used in the per-row heading, never as a duplicate
    # field below it.
    "coded_title",
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


_ICD10_VALUE_PATTERN = re.compile(r"^[A-TV-Z]\d{2}[A-Z0-9]*$", re.IGNORECASE)


def condition_text(val: Any) -> str:
    """'<text> (<ICD10>)' for a condition/diagnose dict, text-only if no code.

    Unstructured free-text entries (e.g. ``value="random unstructured"``)
    don't have an ICD-10 code; we used to feed any string ``value`` to
    ``format_icd10_code`` which jammed a dot after the third character —
    producing nonsense like "RAN.DOM UNSTRUCTURED". The regex guard now
    confirms the value looks like a real ICD-10 code (e.g. ``E11649``,
    ``K635``, ``N390``) before formatting; everything else is dropped.
    """
    if not isinstance(val, dict):
        return value_to_text(val)
    text = (val.get("text") or val.get("display") or "").strip()
    annotations = val.get("annotations") or []
    icd10_raw = val.get("value")
    icd10 = ""
    if annotations:
        first = annotations[0]
        if isinstance(first, str) and first.strip() and _ICD10_VALUE_PATTERN.match(first.strip().replace(".", "")):
            icd10 = first.strip()
    if not icd10 and isinstance(icd10_raw, str) and icd10_raw.strip():
        candidate = icd10_raw.strip()
        if _ICD10_VALUE_PATTERN.match(candidate.replace(".", "")):
            icd10 = candidate
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


def _metadata_blocks(entry: Any) -> list[dict]:
    """Render the CommandMetadata rows the extractor attached on `_metadata`.

    Each row becomes a `field` block — the metadata `key` is shown as the
    field label (replacing underscores with spaces for legibility), and the
    `value` is the field value. Returns ``[]`` when there's no metadata so
    the calling code stays simple.
    """
    if not isinstance(entry, dict):
        return []
    metas = entry.get("_metadata")
    if not isinstance(metas, list) or not metas:
        return []
    out: list[dict] = []
    for m in metas:
        if not isinstance(m, dict):
            continue
        key = (m.get("key") or "").strip()
        value = (m.get("value") or "").strip()
        if not key and not value:
            continue
        label = format_field_label(key.replace(":", "_")) if key else ""
        out.append({"kind": "field", "label": label or "METADATA", "value": value})
    return out


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


def _escape_attr(value: Any) -> str:
    """Escape a string for safe interpolation into an HTML attribute value
    inside a ``body_html`` block (rendered with ``|safe``). Notably turns the
    ``&`` query-param separators in a presigned S3 URL into ``&amp;`` so the
    ``src`` attribute is valid HTML and can't break out of its quotes."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


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
        out.append(_heading("Assess Condition", condition_text(a.get("condition", {}))))
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
        # Match the Canvas UI's field order: SHOW ON CONDITION LIST first,
        # then RATIONALE. Canvas labels the toggle "SHOW ON CONDITION LIST"
        # (the JSON key is `show_in_condition_list`).
        if "show_in_condition_list" in cmd_data:
            flag = cmd_data.get("show_in_condition_list")
            shown = ("Yes" if flag else "No") if isinstance(flag, bool) else str(flag)
            out.append(_field("SHOW ON CONDITION LIST", shown))
        if rationale := cmd_data.get("rationale"):
            out.append(_field("RATIONALE", rationale))
        out.extend(extra_blocks(
            cmd_data, shown_keys={"condition", "rationale", "show_in_condition_list"},
        ))
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
    """Shared renderer for prescribe / refill / stop / adjust / change medication.

    For ``adjustPrescription`` the entry carries both ``prescribe`` (the
    current med) and an optional ``change_medication_to`` (the new med).
    Canvas's UI keeps the *current* med in the heading and surfaces the
    change via a ``CHANGE MEDICATION TO`` field — we mirror that here.
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        # For adjustPrescription, the heading is the CURRENT med (`prescribe`),
        # not the new one. For other med actions, fall back to the default
        # title resolution which picks the most specific field.
        cm_to = entry.get("change_medication_to")
        cm_text = value_to_text(cm_to) if cm_to else ""
        prev_text = value_to_text(entry.get("prescribe"))
        if cm_text and prev_text and cm_text != prev_text:
            heading_value = prev_text
        else:
            heading_value = medication_title(entry)
        out.append(_heading_or_plain(display_name, heading_value))

        if cm_text and prev_text and cm_text != prev_text:
            out.append(_field("CHANGE MEDICATION TO", cm_text))

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
        out.append(_heading("Refer", value_to_text(r.get("refer_to"))))
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

        # Match Canvas's field order: COMMENT prints before any per-test
        # AOE "NEW QUESTION" rows.
        if comment := lo.get("comment"):
            out.append(_field("COMMENT", comment))

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
        # Match the Canvas UI's field order: INTERNAL COMMENT comes before
        # ORDERING PROVIDER.
        if comment := io.get("comment"):
            out.append(_field("INTERNAL COMMENT", comment))
        if op_text := value_to_text(io.get("ordering_provider")):
            out.append(_field("ORDERING PROVIDER", op_text))
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
        # Reference data — the underlying LabReport / ImagingReport /
        # ReferralReport / UncategorizedClinicalDocument content, stamped on
        # the entry as pre-rendered HTML by the extractor's
        # ``_attach_*_review_reference_html`` helpers. Surfaces inline after
        # the review's own fields instead of in a separate trailing
        # "Reference Data" section like home-app does.
        if ref_html := entry.get("_reference_html"):
            out.append({"kind": "body_html", "value": ref_html})
    return out


def _blocks_reference(display_name: str, data: Any) -> list[dict]:
    """Reference command: a saved diagnostic-view snapshot (e.g. a lab-trend
    table). Renders ``Reference: <name>`` followed by the pre-rendered HTML
    table stored on the command — matching how it reads in the note. The
    internal ``diagnostic_view_id`` is deliberately not surfaced.
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = value_to_text(entry.get("name"))
        out.append(_heading_or_plain("Reference", title))
        html = (
            _decode_custom_content(entry.get("print_content"))
            or _decode_custom_content(entry.get("content"))
        )
        if html:
            # `body_html` renders with |safe; reference content is
            # platform-generated diagnostic-view HTML (a values table).
            out.append({"kind": "body_html", "value": html})
        out.extend(extra_blocks(entry, shown_keys={
            "name", "diagnostic_view_id", "diagnostic_view", "content", "print_content",
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
        # `lot_number` is a coded-value dict (``{text, extra, value, ...}``);
        # ``value_to_text`` unwraps to the human-facing string. ``str(lot)``
        # was previously dumping the whole dict.
        if lot_text := (value_to_text(entry.get("lot_number")) or "").strip():
            out.append(_field("LOT NUMBER", lot_text))
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


def _format_coded_pair(entry: dict) -> str:
    """Render a `{code, display}` entry as ``CODE — display`` (or just CODE)."""
    code = str(entry.get("code") or "").strip()
    display = str(entry.get("display") or "").strip()
    if code and display:
        return f"{code} — {display}"
    return display or code


def _blocks_billing(display_name: str, data: Any) -> list[dict]:
    """Patient-facing billed services: CPT (+ modifiers) and description, with
    units, the modifier display names, and any ICD-10 diagnoses linked through
    the line item's Assessments.

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
        modifiers = item.get("modifiers") or []
        modifier_parts = [
            _format_coded_pair(m) for m in modifiers if isinstance(m, dict)
        ]
        modifier_parts = [p for p in modifier_parts if p]
        if modifier_parts:
            out.append(_field("MODIFIERS", "; ".join(modifier_parts)))
        diagnoses = item.get("diagnoses") or []
        diagnosis_parts = [
            _format_coded_pair(d) for d in diagnoses if isinstance(d, dict)
        ]
        diagnosis_parts = [p for p in diagnosis_parts if p]
        if diagnosis_parts:
            out.append(_field("RELATED DIAGNOSES", "; ".join(diagnosis_parts)))
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
        # Canvas UI labels this field "COMMENT" even though the underlying
        # JSON key is `narrative` — match the visible label.
        if narrative := entry.get("narrative"):
            out.append(_field("COMMENT", narrative))
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
        # Keep the trailing category qualifier (e.g., "Sage (allergy group)")
        # that Canvas writes into `data.allergy.text` — useful context for
        # whether the entry is an allergy group, ingredient, or medication.
        name = value_to_text(a.get("allergy"))
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


# ---- New block builders -----------------------------------------------------

# Friendly-name lookup for chart sections — keeps the printout from showing
# raw enum keys like "family_histories".
_CHART_SECTION_LABELS: dict[str, str] = {
    "conditions": "Conditions",
    "medications": "Medications",
    "allergies": "Allergies",
    "immunizations": "Immunizations",
    "family_histories": "Family History",
    "surgical_history": "Surgical History",
    "medical_history": "Past Medical History",
    "goals": "Goals",
    "vitals": "Vitals",
}


def _humanize_section(value: Any) -> str:
    raw = (value_to_text(value) or "").strip()
    if not raw:
        return ""
    if raw in _CHART_SECTION_LABELS:
        return _CHART_SECTION_LABELS[raw]
    return raw.replace("_", " ").title()


def _blocks_chart_section_review(display_name: str, data: Any) -> list[dict]:
    """One row per reviewed chart section, with the list of reviewed items
    beneath the heading (e.g., every condition under "Reviewed: Conditions").

    The reviewed-items list is pre-rendered server-side and stored on
    ``ChartSectionReview.content``; the extractor splits it into a
    ``section_content`` list (one item per line) on each entry — see
    ``NoteDataExtractor._attach_chart_section_review_content``. When the
    anchor review can't be resolved (``section_content`` absent) we fall back
    to the heading alone.
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        section = entry.get("section_label") or _humanize_section(entry.get("section"))
        out.append(_heading("Reviewed", section or "Section"))
        for item in entry.get("section_content") or []:
            if text := value_to_text(item):
                out.append(_body(text))
        out.extend(extra_blocks(entry, shown_keys={"section", "section_label", "section_content"}))
    return out


def _blocks_close_goal(display_name: str, data: Any) -> list[dict]:
    """Close-goal entries: target goal + achievement status + progress note."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        goal = entry.get("goal_id") if isinstance(entry.get("goal_id"), dict) else {}
        title = value_to_text(goal) or value_to_text(entry.get("goal_statement"))
        out.append(_heading("Close Goal", title))
        status = (entry.get("achievement_status") or "").strip()
        if status:
            out.append(_field("STATUS", status.replace("_", " ").title()))
        if progress := (entry.get("progress") or "").strip():
            out.append(_field("PROGRESS / BARRIERS", progress))
        out.extend(extra_blocks(
            entry, shown_keys={"goal_id", "achievement_status", "progress"},
        ))
    return out


def _blocks_poc_lab_test(display_name: str, data: Any) -> list[dict]:
    """POC lab test: template name in heading, indications, per-field test
    values in template order with units, then comments — mirrors the Canvas
    command UI exactly. Empty rows are kept so the print matches the
    on-screen panel, where blank measurements still render with their label."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        template = entry.get("template") if isinstance(entry.get("template"), dict) else {}
        title = value_to_text(template.get("text")) or value_to_text(template)
        out.append(_heading("POC Lab Test", title))

        indications = entry.get("indications")
        if isinstance(indications, list) and indications:
            formatted = [_format_diagnosis_with_icd(i) for i in indications]
            formatted = [f for f in formatted if f]
            if formatted:
                out.append(_field("INDICATIONS", ", ".join(formatted)))

        # Render per-measurement rows in the order defined on the template
        # (template.extra.fields). The dict keys are `test_values|<label_lower>`.
        shown_test_value_keys: set[str] = set()
        fields = (template.get("extra") or {}).get("fields") if isinstance(template.get("extra"), dict) else None
        if isinstance(fields, list):
            for f in fields:
                if not isinstance(f, dict):
                    continue
                label = (f.get("label") or "").strip()
                if not label:
                    continue
                key = f"test_values|{label.lower()}"
                shown_test_value_keys.add(key)
                units = (f.get("units") or "").strip()
                display_label = f"{label.upper()} ({units.upper()})" if units else label.upper()
                out.append(_field(display_label, value_to_text(entry.get(key))))
        # Catch any test_values keys not declared on the template (shouldn't
        # happen in practice but keeps us safe if the template definition drifts
        # from the saved data).
        for key, val in entry.items():
            if not isinstance(key, str) or not key.startswith("test_values|") or key in shown_test_value_keys:
                continue
            shown_test_value_keys.add(key)
            label = key.split("|", 1)[1].strip()
            if label:
                out.append(_field(label.upper(), value_to_text(val)))

        out.append(_field("COMMENTS", value_to_text(entry.get("remarks"))))

        out.extend(extra_blocks(
            entry,
            shown_keys={"template", "indications", "remarks", "value_rows"} | shown_test_value_keys,
        ))
    return out


def _blocks_cancel_prescription(display_name: str, data: Any) -> list[dict]:
    """Cancel-prescription: prescription being cancelled + rationale."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        rx = entry.get("selected_prescription") if isinstance(entry.get("selected_prescription"), dict) else {}
        out.append(_heading("Cancel Prescription", value_to_text(rx)))
        if entry.get("stop_medication"):
            out.append(_field("ALSO STOP MEDICATION", "Yes"))
        if rationale := (entry.get("rationale") or "").strip():
            out.append(_field("RATIONALE", rationale))
        out.extend(extra_blocks(
            entry, shown_keys={"selected_prescription", "rationale", "stop_medication"},
        ))
    return out


# Reason codes used by deny_refill / deny_change. Lifted verbatim from
# home-app/builtin_content/core_types/commands/sdk/deny_refill.py (REASON_CODE_CHOICES)
# and home-app/builtin_content/core_types/commands/deny_change.py — both lists are
# identical. Used to translate the stored 2-letter code into the human-readable
# label that the Canvas command UI shows.
_REFILL_REASON_CODE_DISPLAYS: dict[str, str] = {
    "AA": "Patient unknown to the prescriber",
    "AB": "Patient never under provider care",
    "AC": "Patient no longer under provider care",
    "AD": "Refill too soon",
    "AE": "Medication never prescribed for patient",
    "AF": "Patient should contact provider",
    "AG": "Refill not appropriate",
    "AH": "Patient has picked up prescription",
    "AJ": "Patient has picked up partial fill of prescription",
    "AK": "Patient has not picked up prescription, drug returned to stock",
    "AM": "Patient needs appointment",
    "AN": "Prescriber not associated with this practice or location",
    "AO": "No attempt will be made to obtain Prior Authorization",
    "AP": "Request already responded to by other means (e.g. phone or fax)",
}

_REFILL_RESPONSE_TYPE_DISPLAYS: dict[str, str] = {
    "A": "Approved",
    "D": "Denied",
}


def _blocks_refill_decision(display_name: str, data: Any) -> list[dict]:
    """Approve/deny refill: medication header + prescription-derived read-only
    rows (TOTAL QUANTITY / DIRECTIONS / PHARMACY) + decision body. Mirrors the
    Canvas command UI in ``home-app/builtin_content/core_types/commands/sdk/
    approve_refill.py:63-90`` and ``deny_refill.py:86-114``. The Prescription
    anchor details are stamped onto each entry as ``total_quantity`` /
    ``directions`` / ``pharmacy_display`` by ``NoteDataExtractor.
    _fetch_refill_decision_commands_data``. (Underscore-free names: the
    patient-facing Django template also reads these, and Django blocks
    attribute access on ``_``-leading attribute names.)"""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        rx = entry.get("prescribe") if isinstance(entry.get("prescribe"), dict) else {}
        out.append(_heading(display_name, value_to_text(rx)))

        # Prescription-derived rows — these come from the anchor object and
        # are surfaced above the command's own fields in the Canvas UI.
        if total_quantity := (entry.get("total_quantity") or "").strip():
            out.append(_field("TOTAL QUANTITY", total_quantity))
        if directions := (entry.get("directions") or "").strip():
            out.append(_field("DIRECTIONS", directions))
        if pharmacy := (entry.get("pharmacy_display") or "").strip():
            out.append(_field("PHARMACY", pharmacy))

        response_type = (entry.get("response_type") or "").strip()
        if response_type == "D":
            # Only deny commands show "RESPONSE: Denied" in the Canvas UI —
            # approve's action is implicit in the heading.
            out.append(_field(
                "RESPONSE",
                _REFILL_RESPONSE_TYPE_DISPLAYS.get(response_type, response_type),
            ))

        refills = entry.get("refills")
        if refills not in (None, ""):
            # Label matches the ApproveRefill schema's field label.
            out.append(_field("TOTAL NUMBER OF DISPENSINGS APPROVED", str(refills)))

        if reason_code := (entry.get("reason_code") or "").strip():
            out.append(_field(
                "REASON",
                _REFILL_REASON_CODE_DISPLAYS.get(reason_code, reason_code),
            ))

        if note := (entry.get("note_to_pharmacist") or "").strip():
            out.append(_field("NOTE TO PHARMACIST", note))

        out.extend(extra_blocks(
            entry, shown_keys={
                "prescribe", "refills", "reason_code", "note_to_pharmacist",
                "response_type", "refill_request",
                # Extractor-derived stamps (rendered above as TOTAL QUANTITY /
                # DIRECTIONS / PHARMACY / REASON). Underscore-free because the
                # patient template also reads them — list them here so
                # extra_blocks() doesn't re-emit them as stray fields.
                "total_quantity", "directions", "pharmacy_display",
                "reason_display",
                # noisy plumbing fields not useful in the patient print
                "pharmacy", "prescriber", "days_supply", "indications",
                "substitutions", "type_to_dispense", "supervising_provider",
                "quantity_to_dispense", "sig",
            },
        ))
    return out


def _blocks_change_decision(display_name: str, data: Any) -> list[dict]:
    """Approve/deny change: same shape family as refill decisions."""
    return _blocks_refill_decision(display_name, data)


def _blocks_educational_material(display_name: str, data: Any) -> list[dict]:
    """Patient-education handout: title + language."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = value_to_text(entry.get("title"))
        out.append(_heading("Educational Material", title))
        if lang := value_to_text(entry.get("language")):
            out.append(_field("LANGUAGE", lang))
        out.extend(extra_blocks(entry, shown_keys={"title", "language"}))
    return out


def _blocks_visual_exam_finding(display_name: str, data: Any) -> list[dict]:
    """Visual exam finding: title + narrative + the attached image, so the
    print matches the Canvas UI.

    The extractor resolves the image to a short-lived presigned S3 URL and
    stamps it on the entry as ``image_url`` — see
    ``NoteDataExtractor._attach_visual_exam_finding_image``. We render it as
    an ``<img>`` in a ``body_html`` block; the raw ``image`` filename is never
    surfaced (it's an opaque S3 key). When no image is attached (or the URL
    can't be resolved) we render title + narrative only.
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title") or ""
        out.append(_heading("Visual Exam Finding", title))
        if narrative := (entry.get("narrative") or "").strip():
            out.append(_field("NARRATIVE", narrative))
        if image_url := (entry.get("image_url") or "").strip():
            out.append({
                "kind": "body_html",
                "value": (
                    f'<img src="{_escape_attr(image_url)}" '
                    f'alt="{_escape_attr(title)}" '
                    'class="visual-exam-image" '
                    'style="max-width:100%;max-height:320px;" />'
                ),
            })
        out.extend(extra_blocks(
            entry, shown_keys={"title", "narrative", "image", "image_url"},
        ))
    return out


_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def _decode_custom_content(raw: Any) -> str:
    """Decode the HTML payload stored in customCommand `content` /
    `print_content`. Canvas stores it as base64 when the command is committed
    via the SDK's standard `originate` path (see home-app's
    `standalone/custom_command.py`), but some plugin authors write the raw
    HTML directly. Distinguish heuristically: if the payload looks like pure
    base64 (no HTML/whitespace/structural characters) try a decode; if the
    decoded text starts with something HTML-ish, keep it. Otherwise treat
    the input as already-HTML and return it as-is so plain payloads aren't
    mangled.
    """
    if not isinstance(raw, str) or not raw:
        return ""
    candidate = raw.strip()
    # Raw HTML if it has `<` (markup) or whitespace (line breaks etc.) —
    # base64 has none of those.
    if "<" in candidate[:200] or any(c.isspace() for c in candidate[:200]):
        return raw
    if not _BASE64_PATTERN.match(candidate):
        return raw
    try:
        import base64 as _b64
        decoded = _b64.b64decode(candidate, validate=True).decode("utf-8", errors="replace")
    except Exception:
        return raw
    # If the decode result doesn't read like text/HTML, fall back to raw.
    if "<" not in decoded[:200] and not any(c.isalpha() for c in decoded[:50]):
        return raw
    return decoded


def _coding_gap_title_from_diagnose(entry: dict) -> str:
    """First diagnose formatted as ``<text> (<ICD-10>)``.

    Used for ``createCodingGap`` (where the diagnose IS the gap being
    proposed). Falls back to the detected_issue label if no diagnose is
    populated.
    """
    if not isinstance(entry, dict):
        return ""
    diagnoses = entry.get("diagnose") if isinstance(entry.get("diagnose"), list) else []
    for d in diagnoses:
        formatted = _format_diagnosis_with_icd(d)
        if formatted:
            return formatted
    return value_to_text(entry.get("detected_issue"))


def _coding_gap_title_from_detected_issue(entry: dict) -> str:
    """Detected-issue label.

    Used for ``assessCodingGap`` / ``validateCodingGap`` /
    ``deferCodingGap``, which all act ON an existing detected coding gap.
    The original diagnosis is what identifies the row; the chosen
    diagnosis (if any) lives in the body as a DIAGNOSE field.
    """
    if not isinstance(entry, dict):
        return ""
    return value_to_text(entry.get("detected_issue"))


def _format_status(value: Any) -> str:
    """Normalize a status string the way the Canvas UI does: replace
    underscores with spaces and capitalize only the first letter
    (``create_and_validate`` → ``Create and validate``, not
    ``Create And Validate``)."""
    text = (value_to_text(value) or "").strip()
    if not text:
        return ""
    text = text.replace("_", " ")
    return text[:1].upper() + text[1:]


def _format_diagnosis_with_icd(d: Any) -> str:
    """Render a diagnose entry as `<text> (<ICD-10>)` — same convention as
    condition_text — but tolerates the coding-gap data shape where the code
    lives in `annotations[0]`."""
    if not isinstance(d, dict):
        return value_to_text(d)
    text = (d.get("text") or d.get("display") or "").strip()
    code = ""
    annotations = d.get("annotations") or []
    if annotations and isinstance(annotations[0], str):
        code = annotations[0].strip()
    if not code and isinstance(d.get("value"), str):
        # `value` is usually an unformatted ICD-10 like "N390"; format with dot.
        code = format_icd10_code(d["value"].strip())
    if text and code:
        return f"{text} ({code})"
    return text or code


def _blocks_create_coding_gap(display_name: str, data: Any) -> list[dict]:
    """Create-coding-gap: matches Canvas's STATUS → DATE → NOTE order.

    Title is the proposed diagnose (the gap being created). Additional
    diagnoses (when the user picks more than one) trail in the body.
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        diagnoses = entry.get("diagnose") if isinstance(entry.get("diagnose"), list) else []
        formatted = [_format_diagnosis_with_icd(d) for d in diagnoses]
        formatted = [f for f in formatted if f]
        out.append(_heading("Create Coding Gap", formatted[0] if formatted else ""))
        if status := _format_status(entry.get("status")):
            out.append(_field("STATUS", status))
        if date := (entry.get("date") or "").strip():
            out.append(_field("DATE", date))
        if note := (entry.get("details") or "").strip():
            out.append(_field("NOTE", note))
        if len(formatted) > 1:
            out.append(_field("ADDITIONAL DIAGNOSES", "; ".join(formatted[1:])))
        out.extend(extra_blocks(
            entry, shown_keys={"diagnose", "date", "status", "details"},
        ))
    return out


def _blocks_assess_coding_gap(display_name: str, data: Any) -> list[dict]:
    """Assess-coding-gap: matches Canvas's
    STATUS → NOTE → DIAGNOSE → BACKGROUND → APPROX DATE OF ONSET →
    TODAY'S ASSESSMENT order.

    Title is the *detected* issue (the gap being assessed). The diagnose
    field is the *adopted* condition shown in-body as DIAGNOSE.
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading("Assess Coding Gap", value_to_text(entry.get("detected_issue"))))
        if status := _format_status(entry.get("status")):
            out.append(_field("STATUS", status))
        if note := (entry.get("details") or "").strip():
            out.append(_field("NOTE", note))
        diagnoses = entry.get("diagnose") if isinstance(entry.get("diagnose"), list) else []
        formatted = [_format_diagnosis_with_icd(d) for d in diagnoses]
        formatted = [f for f in formatted if f]
        if formatted:
            out.append(_field("DIAGNOSE", "; ".join(formatted)))
        if bg := (entry.get("background") or "").strip():
            out.append(_field("BACKGROUND", bg))
        if onset := entry.get("approximate_date_of_onset"):
            if isinstance(onset, dict):
                date = (onset.get("date") or "").strip()
                input_text = (onset.get("input") or "").strip()
                if input_text and date and input_text != date:
                    onset_text = f"{input_text} (around {date})"
                else:
                    onset_text = input_text or date
                if onset_text:
                    out.append(_field("APPROXIMATE DATE OF ONSET", onset_text))
        if ta := (entry.get("todays_assessment") or "").strip():
            out.append(_field("TODAY'S ASSESSMENT", ta))
        out.extend(extra_blocks(
            entry,
            shown_keys={
                "diagnose", "detected_issue", "status", "approximate_date_of_onset",
                "background", "todays_assessment", "details",
            },
        ))
    return out


def _blocks_validate_coding_gap(display_name: str, data: Any) -> list[dict]:
    """Validate-coding-gap: STATUS → DATE → NOTE order (matches Canvas)."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading("Validate Coding Gap", value_to_text(entry.get("detected_issue"))))
        if status := _format_status(entry.get("status")):
            out.append(_field("STATUS", status))
        if date := (entry.get("date") or "").strip():
            out.append(_field("DATE", date))
        if note := (entry.get("details") or "").strip():
            out.append(_field("NOTE", note))
        out.extend(extra_blocks(
            entry, shown_keys={"detected_issue", "status", "date", "details"},
        ))
    return out


def _blocks_defer_coding_gap(display_name: str, data: Any) -> list[dict]:
    """Defer-coding-gap: detected issue snoozed for later review."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading("Defer Coding Gap", value_to_text(entry.get("detected_issue"))))
        out.extend(extra_blocks(entry, shown_keys={"detected_issue"}))
    return out


def _blocks_clipboard(display_name: str, data: Any) -> list[dict]:
    """Clipboard: a free-form multi-line text scratch the provider added
    to the note (no fixed schema beyond `text`)."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        text = (entry.get("text") or "").strip()
        out.append(_heading_or_plain("Clipboard", ""))
        if text:
            out.append(_body(text))
        out.extend(extra_blocks(entry, shown_keys={"text"}))
    return out


def _blocks_snooze_protocol(display_name: str, data: Any) -> list[dict]:
    """Snooze-protocol: matches Canvas's
    SNOOZE UNTIL → REASON → COMMENT order and label."""
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(_heading("Snooze Protocol", value_to_text(entry.get("protocol"))))
        if until := (entry.get("snooze_until_date") or "").strip():
            out.append(_field("SNOOZE UNTIL", until))
        if reason := value_to_text(entry.get("snooze_reason")):
            out.append(_field("REASON", reason))
        if comment := (entry.get("snooze_comment") or "").strip():
            out.append(_field("COMMENT", comment))
        out.extend(extra_blocks(
            entry,
            shown_keys={"protocol", "snooze_reason", "snooze_until_date", "snooze_comment"},
        ))
    return out


def _humanize_schema_key(key: str) -> str:
    """Turn ``observationSummary`` / ``health_risk_assessment_summary`` into
    ``Observation Summary`` / ``Health Risk Assessment Summary``."""
    if not key:
        return ""
    # camelCase → "camel Case"
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key)
    spaced = spaced.replace("_", " ").replace("-", " ").strip()
    return " ".join(w.capitalize() for w in spaced.split())


def _blocks_custom_command(display_name: str, data: Any) -> list[dict]:
    """Plugin-authored custom command. Renders the HTML payload stored on
    ``data.content`` / ``data.print_content`` (sometimes base64-encoded,
    sometimes raw HTML — see :func:`_decode_custom_content`).

    Heading uses ``label`` → ``title`` → humanized ``_schema_key`` →
    ``display_name``. The ``label`` is either set on the command instance or
    stamped from the registered ``PluginCommand.label`` by
    ``NoteDataExtractor._attach_plugin_command_details`` — so the heading reads
    with the exact branding the plugin author chose. The humanized
    ``_schema_key`` fallback only kicks in when no ``PluginCommand`` row
    matches (e.g. a bare ``customCommand`` with no registered label).
    """
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        schema_key = entry.get("_schema_key") or ""
        title = (
            value_to_text(entry.get("label"))
            or value_to_text(entry.get("title"))
            or _humanize_schema_key(schema_key)
        )
        if title and title != display_name:
            out.append(_heading(display_name, title))
        else:
            out.append(_heading_or_plain(display_name, ""))
        html = _decode_custom_content(entry.get("print_content")) or _decode_custom_content(entry.get("content"))
        if html:
            # `body_html` is rendered with |safe in command_block.html so the
            # decoded HTML payload from the plugin author renders as markup,
            # not escaped text. customCommand content is platform-trusted
            # (only plugin authors can produce it).
            out.append({"kind": "body_html", "value": html})
        out.extend(extra_blocks(
            entry,
            shown_keys={
                "label", "title", "content", "print_content", "schema_key",
                "_schema_key",
            },
        ))
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
    "cancel_prescription": _blocks_cancel_prescription,
    "refill_decision": _blocks_refill_decision,
    "change_decision": _blocks_change_decision,
    "refer": _blocks_refer,
    "lab_order": _blocks_lab_order,
    "imaging_order": _blocks_imaging_order,
    "poc_lab_test": _blocks_poc_lab_test,
    "review": _blocks_review,
    "reference": _blocks_reference,
    "chart_section_review": _blocks_chart_section_review,
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
    "close_goal": _blocks_close_goal,
    "allergy": _blocks_allergy,
    "educational_material": _blocks_educational_material,
    "visual_exam_finding": _blocks_visual_exam_finding,
    "custom_command": _blocks_custom_command,
    "create_coding_gap": _blocks_create_coding_gap,
    "assess_coding_gap": _blocks_assess_coding_gap,
    "validate_coding_gap": _blocks_validate_coding_gap,
    "defer_coding_gap": _blocks_defer_coding_gap,
    "snooze_protocol": _blocks_snooze_protocol,
    "clipboard": _blocks_clipboard,
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
    "reference": lambda e: value_to_text(e.get("name")) if isinstance(e, dict) else "",
    "chart_section_review": lambda e: _humanize_section(e.get("section")),
    "med_action": medication_title,
    "prescribe": medication_title,
    "cancel_prescription": lambda e: value_to_text(e.get("selected_prescription")),
    "refill_decision": lambda e: value_to_text(e.get("prescribe")),
    "change_decision": lambda e: value_to_text(e.get("prescribe")) or value_to_text(e.get("medication")),
    "refer": lambda e: value_to_text(e.get("refer_to")),
    "lab_order": lambda e: value_to_text(e.get("lab_partner")),
    "imaging_order": lambda e: value_to_text(e.get("image")),
    "poc_lab_test": lambda e: value_to_text((e.get("template") or {}).get("text") if isinstance(e.get("template"), dict) else e.get("template")),
    "task": lambda e: e.get("title", ""),
    "instruct": lambda e: value_to_text(e.get("instruct")),
    "goal": _title_goal,
    "close_goal": lambda e: value_to_text(e.get("goal_id")) or value_to_text(e.get("goal_statement")),
    "allergy": lambda e: value_to_text(e.get("allergy")),
    "immunize": immunize_title,
    "perform": lambda e: value_to_text(e.get("perform")),
    "medical_history": lambda e: condition_text(e.get("past_medical_history")),
    "surgical_history": lambda e: condition_text(e.get("past_surgical_history")),
    "immunization_statement": lambda e: first_text_from_keys(e, IMMUNIZATION_STATEMENT_TITLE_KEYS),
    "family_history": _title_family_history,
    "remove_allergy": lambda e: value_to_text(e.get("allergy")),
    "medication_statement": lambda e: value_to_text(e.get("medication") or e.get("fdbMedId")),
    "educational_material": lambda e: value_to_text(e.get("title")),
    "visual_exam_finding": lambda e: (e.get("title") or "") if isinstance(e, dict) else "",
    # Title-extractor for custom commands: prefer the label (set on the
    # command instance, or stamped from the registered ``PluginCommand.label``
    # by ``_attach_plugin_command_details``), then ``title``, then a humanized
    # version of the schema_key (e.g., ``observationSummary`` → "Observation
    # Summary") as a last resort when no PluginCommand row matches.
    "custom_command": lambda e: (
        value_to_text(e.get("label"))
        or value_to_text(e.get("title"))
        or _humanize_schema_key(e.get("_schema_key") or "")
    ),
    "create_coding_gap": _coding_gap_title_from_diagnose,
    "assess_coding_gap": _coding_gap_title_from_detected_issue,
    "validate_coding_gap": _coding_gap_title_from_detected_issue,
    "defer_coding_gap": _coding_gap_title_from_detected_issue,
    "snooze_protocol": lambda e: value_to_text(e.get("protocol")),
    "clipboard": lambda e: (e.get("text") or "").strip().splitlines()[0] if isinstance(e, dict) and (e.get("text") or "").strip() else "",
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
            ("questionnaire_data", "Questionnaire", "questionnaire"),
            # Plugin commands the author registered under the Subjective
            # section (PluginCommand.section == "subjective").
            ("custom_commands_subjective", "Custom Command", "custom_command"),
        ],
    },
    {
        "key": "objective",
        "title": "Objective",
        "items": [
            ("vitals_commands_data", "Vitals", "vitals"),
            ("physical_exam_data", "Physical Exam", "exam"),
            ("visual_exam_finding_commands_data", "Visual Exam Finding", "visual_exam_finding"),
            ("custom_commands_objective", "Custom Command", "custom_command"),
        ],
    },
    {
        "key": "assessment",
        "title": "Assessment",
        "items": [
            ("assessments_commands_data", "Assess Condition", "assess"),
            ("diagnose_commands_data", "Diagnose", "diagnose"),
            ("structured_assessment_data", "Structured Assessment", "structured_assessment"),
            ("resolve_condition_commands_data", "Resolve Condition", "resolve_condition"),
            ("change_diagnosis_commands_data", "Change Diagnosis", "change_diagnosis"),
            # Coding-gap workflow is part of the diagnosis story (proposed
            # dx → assessed/accepted → validated → deferred), so render
            # alongside the rest of the Assessment items rather than as a
            # separate billing-adjacent section.
            ("create_coding_gap_commands_data", "Create Coding Gap", "create_coding_gap"),
            ("assess_coding_gap_commands_data", "Assess Coding Gap", "assess_coding_gap"),
            ("validate_coding_gap_commands_data", "Validate Coding Gap", "validate_coding_gap"),
            ("defer_coding_gap_commands_data", "Defer Coding Gap", "defer_coding_gap"),
            ("custom_commands_assessment", "Custom Command", "custom_command"),
        ],
    },
    {
        "key": "reviews",
        "title": "Reviews",
        "items": [
            ("lab_reviews", "Lab Review", "review"),
            ("imaging_reviews", "Imaging Review", "review"),
            ("consult_report_reviews", "Consult Report Review", "review"),
            ("uncategorized_document_reviews", "Uncategorized Document Review", "review"),
            ("chart_section_review_commands_data", "Chart Section Review", "chart_section_review"),
            ("reference_commands_data", "Reference", "reference"),
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
            ("cancel_prescription_commands_data", "Cancel Prescription", "cancel_prescription"),
            ("approve_refill_commands_data", "Approve Refill", "refill_decision"),
            ("deny_refill_commands_data", "Deny Refill", "refill_decision"),
            ("approve_change_commands_data", "Approve Change", "change_decision"),
            ("deny_change_commands_data", "Deny Change", "change_decision"),
            ("referral_commands_data", "Refer", "refer"),
            ("lab_order_commands_data", "Lab Order", "lab_order"),
            ("imaging_order_commands_data", "Image", "imaging_order"),
            ("poc_lab_test_commands_data", "POC Lab Test", "poc_lab_test"),
            ("instruct_commands_data", "Instruct", "instruct"),
            ("educational_material_commands_data", "Educational Material", "educational_material"),
            ("task_commands_data", "Task", "task"),
            ("goal_commands_data", "Goal", "goal"),
            ("update_goal_commands_data", "Update Goal", "goal"),
            ("close_goal_commands_data", "Close Goal", "close_goal"),
            ("snooze_protocol_commands_data", "Snooze Protocol", "snooze_protocol"),
            ("clipboard_commands_data", "Clipboard", "clipboard"),
            ("custom_commands_plan", "Custom Command", "custom_command"),
        ],
    },
    {
        "key": "procedures",
        "title": "Procedures",
        "items": [
            ("immunize_commands_data", "Immunize", "immunize"),
            ("perform_commands_data", "Perform", "perform"),
            ("custom_commands_procedures", "Custom Command", "custom_command"),
        ],
    },
    {
        "key": "history",
        "title": "History",
        "items": [
            ("allergy_commands_data", "Allergy", "allergy"),
            ("remove_allergy_commands_data", "Remove Allergy", "remove_allergy"),
            ("medication_statement_commands_data", "Medication Statement", "medication_statement"),
            ("immunization_statement_commands_data", "Immunization Statement", "immunization_statement"),
            ("patient_family_history_commands_data", "Family History", "family_history"),
            ("medical_history_commands_data", "Past Medical History", "medical_history"),
            ("surgical_history_commands_data", "Past Surgical History", "surgical_history"),
            ("custom_commands_history", "Custom Command", "custom_command"),
        ],
    },
    {
        "key": "custom",
        "title": "Custom Commands",
        "items": [
            # Fallback bucket: plugin commands with no recognized
            # PluginCommand.section (or the provider-only "internal" section),
            # plus bare customCommand rows with no registered row to look up.
            ("custom_commands_data", "Custom Command", "custom_command"),
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
                            {"title": str, "blocks": list[dict], "raw": dict,
                             "command_uuid": str | None},
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
            per_entry = []
            for idx, entry in enumerate(entries):
                blocks = build_blocks(display_name, render_type, [entry])
                # `Command.custom_html` (new field, per docs at
                # https://docs.canvasmedical.com/sdk/data-command/#command —
                # "stores HTML content that is rendered alongside the command
                # in the note") is stamped on the entry as ``_custom_html`` by
                # the extractor. Insert it as a ``body_html`` block right
                # after the heading (and before INDICATIONS / fields / etc.)
                # so plugin authors' custom rendering appears in the print at
                # the same position the Canvas command UI shows it.
                if isinstance(entry, dict):
                    if custom_html := entry.get("_custom_html"):
                        insert_at = 1 if blocks and blocks[0].get("kind", "").startswith("heading") else 0
                        blocks.insert(insert_at, {"kind": "body_html", "value": custom_html})
                # CommandMetadata rows the extractor attached as `_metadata`
                # are kept *separate* from the main blocks so the print UI can
                # toggle them on/off via the "Include command metadata"
                # checkbox. Plugin authors typically store internal workflow
                # state (`workflow_stage`, `external_id`, JSON payloads, etc.)
                # in metadata — see https://docs.canvasmedical.com/sdk/data-command/#commandmetadata —
                # so surfacing it unconditionally would be noisy.
                metadata_blocks = _metadata_blocks(entry)
                per_entry.append({
                    "title": title_for_entry(render_type, display_name, entry, idx),
                    "blocks": blocks,
                    "metadata_blocks": metadata_blocks,
                    "raw": entry,
                    # The command's note-body UUID (when known), so print UIs can
                    # order entries by `Note.body`. None for synthesized/derived
                    # entries with no backing command.
                    "command_uuid": (
                        entry.get("_command_uuid") if isinstance(entry, dict) else None
                    ),
                })
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
