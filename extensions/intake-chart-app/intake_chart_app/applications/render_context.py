"""Pure-Python helpers that turn the chart-review payload into the dict
Django's render_to_string consumes for templates/intake.html.

Sits next to intake_app.py so the application module stays thin (handle()
returns LaunchModalEffect with render_to_string output) and the context
shape is unit-testable without spinning up the Application class."""
from __future__ import annotations

from typing import Any, Callable

VITALS_FIELDS: list[dict[str, str]] = [
    {"id": "height", "label": "Height", "unit": "in", "step": "0.1"},
    {"id": "weight_lbs", "label": "Weight", "unit": "lb", "step": "0.1"},
    {"id": "blood_pressure_systole", "label": "BP systolic", "unit": "mmHg", "step": "1"},
    {"id": "blood_pressure_diastole", "label": "BP diastolic", "unit": "mmHg", "step": "1"},
    {"id": "pulse", "label": "Pulse", "unit": "bpm", "step": "1"},
    {"id": "body_temperature", "label": "Temperature", "unit": "°F", "step": "0.1"},
    {"id": "respiration_rate", "label": "Respiration rate", "unit": "/min", "step": "1"},
    {"id": "oxygen_saturation", "label": "SpO2", "unit": "%", "step": "1"},
]

PROBLEM_ADD_FIELDS: list[tuple[str, str, str]] = [
    ("icd10_code", "Diagnosis (search by name)", "search:icd10"),
    ("background", "Background / assessment", "text"),
]

ALLERGY_ADD_FIELDS: list[tuple[str, str, str]] = [
    ("allergen_code", "Allergen (search by name)", "search:allergy"),
    ("severity", "Severity", "select:mild,moderate,severe"),
    ("narrative", "Narrative / reaction", "text"),
]

MEDICATION_ADD_FIELDS: list[tuple[str, str, str]] = [
    ("fdb_code", "Medication (search by name)", "search:rxterms"),
    ("sig", "Sig", "text"),
]

# Per-section action menus on pre-filled rows. ``key`` maps to the JS
# data-row-action attribute and to the reconciler's _edit / _remove
# dispatch; ``label`` is what the MA sees on the button. Confirm is
# omitted entirely — it emitted nothing (no plugin-side way to originate
# a ChartSectionReviewCommand from the chart sidebar pattern) and was
# distracting in UAT. Edit on Allergies / Medications was a
# remove+recreate workaround for the SDK's missing in-place edit
# commands; it was confusing enough in UAT (and partially broken — for
# medications it triggered Stop only, no new MedicationStatement) that
# the affordance was dropped. Remove + Add new covers those workflows.
PROBLEMS_ACTIONS: list[dict[str, str]] = [
    {"key": "remove", "label": "Resolve"},
]
ALLERGIES_ACTIONS: list[dict[str, str]] = [
    {"key": "remove", "label": "Remove"},
]
MEDICATIONS_ACTIONS: list[dict[str, str]] = [
    {"key": "remove", "label": "Remove"},
]

MEDICAL_HISTORY_ADD_FIELDS: list[tuple[str, str, str]] = [
    # ICD-10 search (NLM Clinical Tables). MedicalHistoryCommand only
    # accepts SNOMED / UNSTRUCTURED Coding dicts, so the reconciler
    # submits ICD-10 picks as plain "<display> (<code>)" free text via
    # ``_icd10_freetext`` — same approach Family History uses.
    ("medical_history_code", "Condition (ICD-10, search by name)", "search:icd10"),
    ("approximate_start_date", "Approximate start date", "date"),
    ("approximate_end_date", "Approximate end date", "date"),
    ("comments", "Comments", "text"),
]

SURGICAL_HISTORY_ADD_FIELDS: list[tuple[str, str, str]] = [
    # ICD-10 search (NLM Clinical Tables). ICD-10-CM is diagnosis-oriented
    # rather than procedure-oriented, but using the same endpoint as the
    # other history sections keeps the modal consistent; the picked value
    # submits as free text via ``_icd10_freetext`` because the SDK's
    # PastSurgicalHistoryCommand only accepts SNOMED Coding dicts.
    ("surgical_history_code", "Procedure (ICD-10, search by name)", "search:icd10"),
    ("approximate_date", "Approximate date", "date"),
    ("comment", "Comment", "text"),
]

FAMILY_HISTORY_ADD_FIELDS: list[tuple[str, str, str]] = [
    ("relative", "Relative",
     "select:Mother,Father,Maternal grandmother,Maternal grandfather,"
     "Paternal grandmother,Paternal grandfather,Sibling(s),Child(ren)"),
    # ICD-10 search (same NLM Clinical Tables endpoint the Problems section
    # uses). FamilyHistoryCommand only accepts SNOMED or UNSTRUCTURED Codings,
    # so the reconciler submits ICD-10 picks as plain "<display> (<code>)"
    # free text — see ``FamilyHistorySection._add``.
    ("family_history_code", "Condition (ICD-10, search by name)", "search:icd10"),
    ("note", "Note", "text"),
]


def summarise_problem(row: dict[str, Any]) -> str:
    display = (row.get("display") or "").strip()
    code = (row.get("code") or "").strip()
    return f"{display} ({code})" if code else display


def summarise_allergy(row: dict[str, Any]) -> str:
    allergen = (row.get("allergen") or "").strip()
    severity = (row.get("severity") or "").strip()
    return f"{allergen} — {severity}" if severity else allergen


def summarise_medication(row: dict[str, Any]) -> str:
    display = (row.get("display") or "").strip()
    sig = (row.get("sig") or "").strip()
    return f"{display} — {sig}" if sig else display


def _field_dicts(fields: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for field_id, label, kind in fields:
        entry: dict[str, Any] = {"id": field_id, "label": label, "kind": kind}
        if kind == "textarea":
            entry["kind_prefix"] = "textarea"
        elif kind == "date":
            entry["kind_prefix"] = "date"
        elif kind.startswith("select:"):
            entry["kind_prefix"] = "select"
            entry["options"] = [
                o.strip() for o in kind.split(":", 1)[1].split(",") if o.strip()
            ]
        elif kind.startswith("search:"):
            entry["kind_prefix"] = "search"
            entry["search_kind"] = kind.split(":", 1)[1]
        else:
            entry["kind_prefix"] = "text"
        out.append(entry)
    return out


def _active_list_rows(
    raw_rows: list[dict[str, Any]],
    *,
    row_prefix: str,
    summarise: Callable[[dict[str, Any]], str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in raw_rows:
        row_id = row.get("id")
        if not row_id:
            continue
        rows.append({
            "row_id": f"{row_prefix}:{row_id}",
            "label": summarise(row),
        })
    return rows


def _history_section_rows(
    raw_rows: list[dict[str, Any]], *, row_prefix: str
) -> list[dict[str, str]]:
    """Reshape prior-chart history rows from ``chart_review.prior_*``
    (which already produces ``{id, summary, data}``) into the
    ``{row_id, label}`` shape the intake template consumes. The row_prefix
    distinguishes pre-filled chart rows from "new:..." add rows in the
    saved form-state."""
    rows: list[dict[str, str]] = []
    for row in raw_rows:
        row_id = row.get("id")
        if not row_id:
            continue
        rows.append({
            "row_id": f"{row_prefix}:{row_id}",
            "label": (row.get("summary") or "").strip(),
        })
    return rows


def _history_items(raw_rows: list[dict[str, Any]]) -> list[str]:
    return [
        (row.get("summary") or "").strip()
        for row in raw_rows
        if (row.get("summary") or "").strip()
    ]


# ATOD Social History form fields. Each entry binds a form-field
# id (the value collected/saved by intake.js) to the bundled questionnaire's
# question code. The reconciler walks ``cmd.questions`` matching by
# ``question_code`` and writes the picked option (radio) or text (textarea)
# via ``q.add_response()``.
ATOD_FORM_FIELDS: list[dict[str, Any]] = [
    {
        "id": "alcohol",
        "label": "Alcohol use",
        "kind": "radio",
        "question_code": "INTAKE_ATOD_ALCOHOL",
        "options": [
            {"value": "never", "label": "Never"},
            {"value": "former", "label": "Former"},
            {"value": "current", "label": "Current"},
        ],
    },
    {
        "id": "tobacco",
        "label": "Tobacco use",
        "kind": "radio",
        "question_code": "INTAKE_ATOD_TOBACCO",
        "options": [
            {"value": "never", "label": "Never"},
            {"value": "former", "label": "Former"},
            {"value": "current", "label": "Current"},
        ],
    },
    {
        "id": "drugs",
        "label": "Other drug use",
        "kind": "radio",
        "question_code": "INTAKE_ATOD_DRUGS",
        "options": [
            {"value": "never", "label": "Never"},
            {"value": "former", "label": "Former"},
            {"value": "current", "label": "Current"},
        ],
    },
    {
        "id": "details",
        "label": "Details (optional)",
        "kind": "textarea",
        "question_code": "INTAKE_ATOD_DETAILS",
        "options": [],
    },
]


def build_intake_context(
    *,
    note_uuid: str,
    patient_id: str,
    note_type_name: str,
    chart: dict[str, Any],
) -> dict[str, Any]:
    """Top-level context builder consumed by
    ``render_to_string('templates/intake.html', context)``."""
    return {
        "note_uuid": note_uuid,
        "patient_id": patient_id,
        "note_type_name": note_type_name or "Note",
        "vitals_fields": VITALS_FIELDS,
        "problems_rows": _active_list_rows(
            chart.get("active_conditions", []),
            row_prefix="condition",
            summarise=summarise_problem,
        ),
        "problems_add_fields": _field_dicts(PROBLEM_ADD_FIELDS),
        "problems_actions": PROBLEMS_ACTIONS,
        "allergies_rows": _active_list_rows(
            chart.get("active_allergies", []),
            row_prefix="allergy",
            summarise=summarise_allergy,
        ),
        "allergies_add_fields": _field_dicts(ALLERGY_ADD_FIELDS),
        "allergies_actions": ALLERGIES_ACTIONS,
        "medications_rows": _active_list_rows(
            chart.get("active_medications", []),
            row_prefix="medication",
            summarise=summarise_medication,
        ),
        "medications_add_fields": _field_dicts(MEDICATION_ADD_FIELDS),
        "medications_actions": MEDICATIONS_ACTIONS,
        "medical_history_rows": _history_section_rows(
            chart.get("prior_medical_history", []), row_prefix="medical_history",
        ),
        "medical_history_add_fields": _field_dicts(MEDICAL_HISTORY_ADD_FIELDS),
        "surgical_history_rows": _history_section_rows(
            chart.get("prior_surgical_history", []), row_prefix="surgical_history",
        ),
        "surgical_history_add_fields": _field_dicts(SURGICAL_HISTORY_ADD_FIELDS),
        "family_history_rows": _history_section_rows(
            chart.get("prior_family_history", []), row_prefix="family_history",
        ),
        "family_history_add_fields": _field_dicts(FAMILY_HISTORY_ADD_FIELDS),
        "atod_form_fields": ATOD_FORM_FIELDS,
        "client_config": {
            "note_uuid": note_uuid,
            "api_base": "/plugin-io/api/intake_chart_app",
        },
    }
