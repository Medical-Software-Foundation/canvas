"""NutritionChartingApp - in-note tab rendering the structured ADIME charting
workflow. Pulls Medical Chart Review auto-populated data, the Phase C
questionnaire-backed sections, and the Phase D single- and multi-command
sections into a single scrolling form."""

from __future__ import annotations

import json
from html import escape
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication
from canvas_sdk.v1.data.note import Note
from django.db import DatabaseError
from logger import log

from nutrition_charting.data.medical_chart_review import build_chart_review
from nutrition_charting.data.multi_command_sections import MULTI_COMMAND_SECTIONS
from nutrition_charting.data.questionnaires import QUESTIONNAIRE_SECTIONS
from nutrition_charting.data.single_command_sections import SINGLE_COMMAND_SECTIONS

NUTRITION_NOTE_KEYWORD = "nutrition"

MEDICAL_CHART_REVIEW_SECTION = "medical_chart_review"
MEDICAL_CHART_REVIEW_FIELDS = ["height", "weight", "bmi", "ubw", "ibw"]

# Display order + titles for the Phase C questionnaire sections. Keeps the
# server-side render and the JS field-restore logic in lockstep.
QUESTIONNAIRE_SECTION_ORDER: list[tuple[str, str]] = [
    ("social_diet_history", "Social and Diet History"),
    ("dietary_intake", "Dietary Intake"),
    ("nfpe", "Nutrition Focused Physical Exam (NFPE)"),
    ("nutrition_diagnosis_pes", "Nutrition Diagnosis (PES)"),
]

# Phase D: master display order interleaving questionnaire + single/multi
# command sections so the form follows the ADIME spec ordering. Each entry is
# (section_id, kind) where kind is one of: questionnaire | single | multi.
SECTION_DISPLAY_ORDER: list[tuple[str, str]] = [
    ("social_diet_history", "questionnaire"),
    ("dietary_intake", "questionnaire"),
    ("nfpe", "questionnaire"),
    ("estimated_nutrition_requirements", "single"),
    ("nutrition_diagnosis_pes", "questionnaire"),
    ("educational_materials", "multi"),
    ("counseling_narrative", "single"),
    ("goals", "multi"),
    ("follow_up_appointment", "single"),
    ("referrals", "multi"),
    ("recommended_labs", "single"),
    ("recommended_supplementation", "single"),
    ("monitor_team_meeting", "single"),
]


def _note_type_name(note_dbid: str | int | None) -> str:
    if not note_dbid:
        return ""
    try:
        note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
    except Note.DoesNotExist:
        return ""
    return (note.note_type_version.name or "").lower()


def is_nutrition_note(note_dbid: str | int | None) -> bool:
    return NUTRITION_NOTE_KEYWORD in _note_type_name(note_dbid)


class NutritionChartingApp(NoteApplication):
    """In-note tab that renders the structured ADIME charting workflow.

    Visible only on note types whose name contains 'nutrition' (case-insensitive).
    """

    NAME = "Nutrition"
    IDENTIFIER = "nutrition_charting__nutrition_charting"

    def visible(self) -> bool:
        return is_nutrition_note(self.event.context.get("note_id"))

    def handle(self) -> list[Effect]:
        note_dbid = self.event.context.get("note_id")
        patient_id = self.event.context.get("patient_id", "") or str(self.event.target.id or "")

        note_uuid = ""
        note_type_name = ""
        if note_dbid:
            try:
                note = Note.objects.select_related("note_type_version").get(dbid=note_dbid)
                note_uuid = str(note.id)
                note_type_name = note.note_type_version.name or ""
            except Note.DoesNotExist:
                log.warning(f"[NutritionChartingApp] Note dbid={note_dbid} not found")

        # One cache dict per request lets the chart-review payload be reused
        # if any other code path fires inside the same handle() invocation.
        cache: dict[str, Any] = {}
        chart = _safe_chart_review(patient_id, cache=cache)

        log.info(
            f"[NutritionChartingApp] handle note_uuid={note_uuid} "
            f"patient_id={patient_id} note_type={note_type_name!r}"
        )
        html = _render_page(
            note_uuid=note_uuid,
            patient_id=patient_id,
            note_type_name=note_type_name,
            chart=chart,
        )
        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.NOTE,
                content=html,
                title="Nutrition",
            ).apply()
        ]


def _safe_chart_review(
    patient_id: str, *, cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Degrade gracefully on transient DB errors so the tab still renders.

    `Patient.DoesNotExist` is handled inside `build_chart_review` and surfaces
    as `{"missing": True}`. Anything other than a `DatabaseError` (e.g.
    AttributeError after a model field rename) propagates so Sentry sees it
    instead of the dietician seeing a silently empty chart-review section.
    """
    if not patient_id:
        return {"missing": True, "patient_id": ""}
    try:
        return build_chart_review(patient_id, cache=cache)
    except DatabaseError as exc:
        log.error(
            f"[NutritionChartingApp] chart review failed: {exc!r}",
            exc_info=True,
        )
        return {"missing": True, "patient_id": patient_id, "error": str(exc)}


# ---------------------------------------------------------------------------
# Rendering helpers — kept small and pure so the page can be unit-tested.
# ---------------------------------------------------------------------------

def _json_for_script(value: Any) -> str:
    """`json.dumps` for content embedded inside an inline `<script>` block.

    `json.dumps` doesn't escape `<`, so an attacker-controlled string
    containing `</script>` (e.g. a Condition `coding.display` planted via
    FHIR/HL7 import) would terminate the script element when interpolated
    raw — breaking out of the JS context into HTML and executing
    attacker-controlled code in the dietician's authenticated session.
    Escaping `<` as the JSON unicode escape `\\u003c` defeats this: the
    HTML tokenizer never sees a `</script` byte sequence, but the JS
    engine decodes `\\u003c` back to `<` when parsing the JSON literal,
    so the original string round-trips intact.
    """
    return json.dumps(value).replace("<", "\\u003c")


def _bullet_list(items: list[str]) -> str:
    if not items:
        return '<p class="nc-empty">None on record.</p>'
    body = "".join(f"<li>{escape(s)}</li>" for s in items if s)
    return f'<ul class="nc-list">{body}</ul>' if body else '<p class="nc-empty">None on record.</p>'


def _info_row(label: str, value: str) -> str:
    return (
        '<div class="nc-info-row">'
        f'<span class="nc-info-label">{escape(label)}</span>'
        f'<span class="nc-info-value">{escape(value) if value else "—"}</span>'
        "</div>"
    )


def _render_pmh(pmh: list[dict[str, str]]) -> str:
    items = []
    for entry in pmh:
        display = (entry.get("display") or "").strip()
        code = (entry.get("code") or "").strip()
        if not display:
            continue
        items.append(f"{display} ({code})" if code else display)
    return _bullet_list(items)


def _render_allergies(allergies: list[dict[str, str]]) -> str:
    items = []
    for a in allergies:
        label = a.get("display") or a.get("narrative") or ""
        severity = a.get("severity") or ""
        items.append(f"{label} — {severity}" if severity else label)
    return _bullet_list(items)


def _render_meds(meds: list[dict[str, str]]) -> str:
    return _bullet_list([m.get("display", "") for m in meds])


def _render_labs(labs: list[dict[str, Any]]) -> str:
    if not labs:
        return '<p class="nc-empty">No nutrition-relevant labs in the last 90 days.</p>'
    rows = "".join(
        "<tr>"
        f"<td>{escape(lab.get('label', ''))}</td>"
        f"<td>{escape(str(lab.get('value', '')))}</td>"
        f"<td>{escape(lab.get('units', ''))}</td>"
        f"<td>{escape(lab.get('effective_date', ''))}</td>"
        "</tr>"
        for lab in labs
    )
    return (
        '<table class="nc-table">'
        "<thead><tr><th>Lab</th><th>Value</th><th>Units</th><th>Date</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _anthro_input(input_id: str, label: str, value: Any, *, readonly: bool = False) -> str:
    val = "" if value is None else escape(str(value))
    ro = " readonly" if readonly else ""
    extra_class = " nc-input--readonly" if readonly else ""
    return (
        '<div class="nc-field">'
        f'<label class="nc-label" for="{input_id}">{escape(label)}</label>'
        f'<input class="nc-input{extra_class}" type="number" step="0.1" '
        f'id="{input_id}" name="{input_id}" value="{val}"{ro}>'
        "</div>"
    )


def _render_chart_review_section(chart: dict[str, Any]) -> str:
    if chart.get("missing"):
        return (
            '<div class="nc-empty-state">'
            "<strong>Patient chart not loaded.</strong>"
            f' <span>(patient_id: <code>{escape(chart.get("patient_id", ""))}</code>)</span>'
            "</div>"
        )

    age = chart.get("age")
    sex = chart.get("sex") or ""
    anthro = chart.get("anthropometrics") or {}
    height = anthro.get("height")
    weight = anthro.get("weight")

    return f"""
<div class="nc-subsection">
  <h3 class="nc-subsection-title">Patient Summary</h3>
  {_info_row("Age", str(age) if age is not None else "")}
  {_info_row("Sex at birth", sex)}
</div>

<div class="nc-subsection">
  <h3 class="nc-subsection-title">Past Medical History</h3>
  {_render_pmh(chart.get("pmh") or [])}
</div>

<div class="nc-subsection">
  <h3 class="nc-subsection-title">Allergies</h3>
  {_render_allergies(chart.get("allergies") or [])}
</div>

<div class="nc-subsection">
  <h3 class="nc-subsection-title">Significant Nutrition Medications</h3>
  {_render_meds(chart.get("medications") or [])}
</div>

<div class="nc-subsection">
  <h3 class="nc-subsection-title">Recent Labs (last 90 days)</h3>
  {_render_labs(chart.get("labs") or [])}
</div>

<div class="nc-subsection">
  <h3 class="nc-subsection-title">Anthropometrics</h3>
  <p class="nc-help">Height and weight pre-fill from the latest chart values; override here if needed. BMI auto-calculates. Saving emits a Vitals command on the note.</p>
  <div class="nc-anthro-grid">
    {_anthro_input("height", "Height (in)", height)}
    {_anthro_input("weight", "Weight (lbs)", weight)}
    {_anthro_input("bmi", "BMI (kg/m²)", "", readonly=True)}
    {_anthro_input("ubw", "Usual Body Weight (lbs)", "")}
    {_anthro_input("ibw", "Ideal Body Weight (lbs)", "")}
  </div>
</div>
"""


def _render_questionnaire_section_body(section_id: str) -> str:
    """Render the form body for a Phase C questionnaire section — all fields
    are free-text textareas keyed to the field IDs in QUESTIONNAIRE_SECTIONS."""
    section = QUESTIONNAIRE_SECTIONS.get(section_id)
    if not section:
        return ""
    rows = section["fields"]
    # NFPE is a single long narrative — give it more vertical space.
    rows_attr = "5" if section_id == "nfpe" else "2"
    parts: list[str] = []
    for field_id, label in rows:
        parts.append(
            '<div class="nc-field nc-field--full">'
            f'<label class="nc-label" for="{escape(field_id)}">{escape(label)}</label>'
            f'<textarea class="nc-input nc-textarea" id="{escape(field_id)}" '
            f'name="{escape(field_id)}" rows="{rows_attr}"></textarea>'
            "</div>"
        )
    return "".join(parts)


def _render_single_command_section_body(section_id: str) -> str:
    """Render the form body for a Phase D single-command section. Field kinds
    drive the input type: number → numeric input, date → date input,
    textarea → multi-line, checkbox → boolean toggle, checklist → multi-select
    of canonical options (data-checklist-target). Anything else falls back to
    a text input."""
    section = SINGLE_COMMAND_SECTIONS.get(section_id)
    if not section:
        return ""
    parts: list[str] = []
    for field_id, label, kind in section["fields"]:
        if kind == "textarea":
            parts.append(
                '<div class="nc-field nc-field--full">'
                f'<label class="nc-label" for="{escape(field_id)}">{escape(label)}</label>'
                f'<textarea class="nc-input nc-textarea" id="{escape(field_id)}" '
                f'name="{escape(field_id)}" rows="2"></textarea>'
                "</div>"
            )
            continue
        if kind == "checkbox":
            parts.append(
                '<div class="nc-field nc-field--full">'
                '<label class="nc-checkbox">'
                f'<input type="checkbox" id="{escape(field_id)}" '
                f'name="{escape(field_id)}" value="true">'
                f' <span>{escape(label)}</span>'
                "</label>"
                "</div>"
            )
            continue
        if kind == "checklist":
            options = section.get("checklist_options") or []
            opt_html = "".join(
                '<label class="nc-checkbox nc-checkbox--inline">'
                f'<input type="checkbox" data-checklist-target="{escape(field_id)}" '
                f'value="{escape(value)}"> <span>{escape(label_text)}</span>'
                "</label>"
                for value, label_text in options
            )
            parts.append(
                '<div class="nc-field nc-field--full">'
                f'<span class="nc-label">{escape(label)}</span>'
                f'<div class="nc-checklist" data-checklist-group="{escape(field_id)}">{opt_html}</div>'
                "</div>"
            )
            continue
        if kind == "number":
            input_type = "number"
            input_attrs = ' step="0.1"'
        elif kind == "date":
            input_type = "date"
            input_attrs = ""
        else:
            input_type = "text"
            input_attrs = ""
        parts.append(
            '<div class="nc-field">'
            f'<label class="nc-label" for="{escape(field_id)}">{escape(label)}</label>'
            f'<input class="nc-input" type="{input_type}"{input_attrs} '
            f'id="{escape(field_id)}" name="{escape(field_id)}" value="">'
            "</div>"
        )
    return "".join(parts)


def _render_multi_command_section_body(section_id: str) -> str:
    """Render the form body for a Phase D pass-2 multi-command section.

    Layout: an empty rows container that JS populates (one row per stored
    entry on form-state load) plus an "add another" button. Educational
    materials gets a canonical-checklist row above the rows container —
    canonical options keep stable row_ids so toggling them on/off across
    saves doesn't mint duplicate Instruct commands.
    """
    section = MULTI_COMMAND_SECTIONS.get(section_id)
    if not section:
        return ""

    parts: list[str] = []
    checklist_options = section.get("checklist_options")
    checklist_field = section.get("checklist_field")
    row_id_prefix = section.get("row_id_prefix", section_id)
    if checklist_options and checklist_field:
        opt_html = "".join(
            '<label class="nc-checkbox nc-checkbox--inline">'
            f'<input type="checkbox" data-multi-canonical="{escape(section_id)}" '
            f'data-row-id="{escape(row_id_prefix)}:{escape(value)}" '
            f'data-name="{escape(label_text)}"> <span>{escape(label_text)}</span>'
            "</label>"
            for value, label_text in checklist_options
        )
        parts.append(
            '<div class="nc-field nc-field--full">'
            '<span class="nc-label">Canonical options</span>'
            f'<div class="nc-checklist">{opt_html}</div>'
            "</div>"
        )

    parts.append(
        f'<div class="nc-multi-rows" data-multi-section="{escape(section_id)}"></div>'
    )
    add_label = section.get("add_row_label", "Add another")
    parts.append(
        '<div class="nc-multi-add">'
        f'<button type="button" class="nc-add-row-btn" data-add-row="{escape(section_id)}">'
        f'+ {escape(add_label)}</button>'
        "</div>"
    )
    return "".join(parts)


def _render_section_block(
    *,
    section_id: str,
    title: str,
    body_html: str,
    save_label: str,
    expanded: bool = True,
) -> str:
    state_class = "nc-section--expanded" if expanded else "nc-section--collapsed"
    return f"""
  <div class="nc-section {state_class}" id="section-{section_id}">
    <div class="nc-section-header" onclick="toggleSection('{section_id}')">
      <span class="nc-section-toggle"></span>
      <span class="nc-section-title">{escape(title)}</span>
      <span class="nc-section-status" id="status-{section_id}"></span>
    </div>
    <div class="nc-section-body">
      <form id="form-{section_id}" onsubmit="return false;">
        {body_html}
        <div class="nc-save-row">
          <button type="button" class="nc-save-btn" data-save-section="{section_id}">{escape(save_label)}</button>
          <span class="nc-status" id="save-status-{section_id}"></span>
          <a href="#" class="nc-refresh-link" id="refresh-link-{section_id}"
             data-refresh-link="{section_id}" hidden>↻ Refresh to see changes</a>
        </div>
      </form>
    </div>
  </div>"""


def _render_page(*, note_uuid: str, patient_id: str, note_type_name: str, chart: dict[str, Any]) -> str:
    safe_note_type = note_type_name or "Nutrition"
    chart_review_body = _render_chart_review_section(chart)
    sections_html = _render_section_block(
        section_id=MEDICAL_CHART_REVIEW_SECTION,
        title="Medical Chart Review",
        body_html=chart_review_body,
        save_label="Save Medical Chart Review",
    )

    # Single render loop driven by SECTION_DISPLAY_ORDER so spec ordering is
    # the only place we maintain it.
    questionnaire_titles = dict(QUESTIONNAIRE_SECTION_ORDER)
    for section_id, kind in SECTION_DISPLAY_ORDER:
        if kind == "questionnaire":
            title = questionnaire_titles.get(section_id, section_id)
            body = _render_questionnaire_section_body(section_id)
        elif kind == "single":
            title = SINGLE_COMMAND_SECTIONS[section_id]["title"]
            body = _render_single_command_section_body(section_id)
        elif kind == "multi":
            title = MULTI_COMMAND_SECTIONS[section_id]["title"]
            body = _render_multi_command_section_body(section_id)
        else:
            continue
        sections_html += _render_section_block(
            section_id=section_id,
            title=title,
            body_html=body,
            save_label=f"Save {title}",
        )

    # Section metadata for the JS — drives form-state restore + save bindings.
    # `flat_field_sections` covers chart_review + questionnaire + single
    # sections (all use flat field-id payloads). Multi-command sections use a
    # separate descriptor below since their payload shape is `{rows: [...]}`.
    flat_field_sections: dict[str, list[dict[str, str]]] = {
        MEDICAL_CHART_REVIEW_SECTION: [
            {"id": fid, "kind": "input"} for fid in MEDICAL_CHART_REVIEW_FIELDS
        ],
    }
    for section_id, _title in QUESTIONNAIRE_SECTION_ORDER:
        flat_field_sections[section_id] = [
            {"id": fid, "kind": "input"}
            for fid, _label in QUESTIONNAIRE_SECTIONS[section_id]["fields"]
        ]
    for section_id, kind in SECTION_DISPLAY_ORDER:
        if kind != "single":
            continue
        flat_field_sections[section_id] = [
            {"id": fid, "kind": fkind}
            for fid, _label, fkind in SINGLE_COMMAND_SECTIONS[section_id]["fields"]
        ]
    flat_fields_js = _json_for_script(flat_field_sections)

    # Build a per-patient ICD-10 option list from the chart's active PMH —
    # used as the `multiselect` options for the referrals row's
    # `indications` field. Each option carries the bare code as the saved
    # value and a "{code} — {display}" label so the dietician can see what
    # they're picking. Empty when the patient has no active conditions.
    pmh_options: list[dict[str, str]] = []
    for entry in (chart.get("pmh") or []):
        if not isinstance(entry, dict):
            continue
        code = (entry.get("code") or "").strip()
        display = (entry.get("display") or "").strip()
        if not code or not display:
            continue
        pmh_options.append({"value": code, "label": f"{code} — {display}"})

    multi_section_descriptors: dict[str, dict[str, Any]] = {}
    for section_id, kind in SECTION_DISPLAY_ORDER:
        if kind != "multi":
            continue
        section = MULTI_COMMAND_SECTIONS[section_id]
        descriptor_fields: list[dict[str, Any]] = []
        for entry in section["row_fields"]:
            # Tolerate the simple 3-tuple shape (no options) and the 4-tuple
            # shape used for select dropdowns: (id, label, "select", options).
            fid, label, fkind = entry[0], entry[1], entry[2]
            field_descriptor: dict[str, Any] = {
                "id": fid, "label": label, "kind": fkind,
            }
            if fkind == "select" and len(entry) > 3:
                field_descriptor["options"] = [
                    {"value": v, "label": opt_label}
                    for v, opt_label in entry[3]
                ]
            elif fkind == "multiselect" and section_id == "referrals" and fid == "indications":
                # Per-patient options threaded in at render time.
                field_descriptor["options"] = list(pmh_options)
            descriptor_fields.append(field_descriptor)
        multi_section_descriptors[section_id] = {
            "row_id_prefix": section.get("row_id_prefix", section_id),
            "row_fields": descriptor_fields,
            "required_fields": list(section.get("required_fields", [])),
        }
    multi_sections_js = _json_for_script(multi_section_descriptors)
    note_uuid_js = repr(note_uuid)  # safely-quoted JS string literal
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ margin: 0; padding: 0; height: 100%; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; color: #1a1a1a; background: #f8f9fa; overflow: hidden; }}
.nc-container {{ width: 100%; height: 100%; padding: 16px; overflow-y: auto; }}
.nc-header {{ display: flex; align-items: center; gap: 12px; padding: 8px 0 12px 0; }}
.nc-badge {{ padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; background: #e8f5e9; color: #2e7d32; }}
.nc-visit-toggle {{ margin-left: auto; display: inline-flex; gap: 12px; font-size: 12px; align-items: center; }}
.nc-visit-toggle label {{ display: inline-flex; gap: 4px; align-items: center; cursor: pointer; }}

.nc-section {{ border: 1px solid #e0e0e0; border-radius: 8px; background: #fff; overflow: hidden; margin-bottom: 8px; }}
.nc-section-header {{ display: flex; align-items: center; padding: 10px 14px; cursor: pointer; background: #fafafa; border-bottom: 1px solid #e0e0e0; user-select: none; }}
.nc-section-header:hover {{ background: #f0f0f0; }}
.nc-section-toggle {{ width: 20px; font-size: 16px; font-weight: 600; color: #2e7d32; }}
.nc-section-title {{ font-weight: 600; font-size: 13px; flex: 1; }}
.nc-section-status {{ font-size: 11px; color: #999; font-weight: 400; }}
.nc-section-status--saved {{ color: #2e7d32; font-weight: 600; }}
.nc-section-status--error {{ color: #d32f2f; font-weight: 600; }}
.nc-section-body {{ padding: 14px; display: none; }}
.nc-section--expanded .nc-section-body {{ display: block; }}
.nc-section--expanded .nc-section-toggle::before {{ content: "−"; }}
.nc-section--collapsed .nc-section-toggle::before {{ content: "+"; }}

.nc-subsection {{ margin-bottom: 14px; }}
.nc-subsection-title {{ font-size: 12px; font-weight: 700; color: #1a1a1a; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 2px solid #e8f5e9; }}
.nc-help {{ font-size: 11px; color: #666; margin-bottom: 8px; }}
.nc-empty {{ font-size: 12px; color: #777; font-style: italic; }}
.nc-empty-state {{ padding: 12px; background: #fff8e1; border: 1px solid #ffe082; border-radius: 4px; font-size: 12px; }}
.nc-list {{ padding-left: 20px; }}
.nc-list li {{ font-size: 12px; line-height: 1.5; }}
.nc-info-row {{ display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #f0f0f0; font-size: 12px; }}
.nc-info-label {{ font-weight: 500; color: #333; }}
.nc-info-value {{ color: #555; }}

.nc-table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
.nc-table th, .nc-table td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }}
.nc-table th {{ font-weight: 600; color: #333; background: #fafafa; }}

.nc-anthro-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
.nc-field {{ display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }}
.nc-field--full {{ width: 100%; }}
.nc-label {{ font-size: 11px; font-weight: 600; color: #333; }}
.nc-input {{ padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; font-family: inherit; background: #fff; }}
.nc-input:focus {{ outline: none; border-color: #2e7d32; box-shadow: 0 0 0 2px rgba(46,125,50,0.15); }}
.nc-input--readonly {{ background: #f5f5f5; color: #555; }}
.nc-textarea {{ width: 100%; resize: vertical; min-height: 36px; }}

.nc-save-row {{ display: flex; align-items: center; margin-top: 14px; padding-top: 10px; border-top: 1px solid #e0e0e0; gap: 12px; }}
.nc-save-btn {{ padding: 6px 16px; background: #2e7d32; color: #fff; border: none; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit; }}
.nc-save-btn:hover {{ background: #1b5e20; }}
.nc-save-btn:disabled {{ background: #a5d6a7; cursor: not-allowed; }}
.nc-status {{ font-size: 11px; font-weight: 500; }}
.nc-status--saving {{ color: #f57c00; }}
.nc-status--saved {{ color: #2e7d32; }}
.nc-status--error {{ color: #d32f2f; }}
.nc-refresh-link {{ font-size: 11px; font-weight: 500; color: #1565c0; text-decoration: none; border-bottom: 1px dashed #1565c0; }}
.nc-refresh-link:hover {{ color: #0d47a1; border-bottom-style: solid; }}
.nc-refresh-link[hidden] {{ display: none; }}

.nc-checkbox {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer; }}
.nc-checkbox--inline {{ margin-right: 14px; }}
.nc-checkbox--ghost {{ color: #999; font-style: italic; }}
.nc-checkbox--ghost input[type=checkbox] {{ accent-color: #999; }}
.nc-checklist {{ display: flex; flex-wrap: wrap; gap: 6px 14px; padding: 6px 0; }}

.nc-multi-rows {{ display: flex; flex-direction: column; gap: 8px; }}
.nc-multi-row {{ display: flex; flex-direction: column; align-items: stretch; gap: 8px; padding: 10px 12px; background: #fafafa; border: 1px solid #e0e0e0; border-radius: 4px; }}
.nc-multi-row .nc-field {{ margin-bottom: 0; }}
.nc-remove-row-btn {{ padding: 4px 10px; background: #fff; color: #c62828; border: 1px solid #ef9a9a; border-radius: 4px; font-size: 11px; cursor: pointer; align-self: flex-end; }}
.nc-remove-row-btn:hover {{ background: #ffebee; }}
.nc-multi-add {{ margin-top: 8px; }}
.nc-add-row-btn {{ padding: 4px 12px; background: #fff; color: #2e7d32; border: 1px dashed #2e7d32; border-radius: 4px; font-size: 12px; cursor: pointer; }}
.nc-add-row-btn:hover {{ background: #e8f5e9; }}

.nc-provider-search {{ position: relative; }}
.nc-provider-input {{ width: 100%; }}
.nc-provider-dropdown {{ position: absolute; left: 0; right: 0; top: 100%; z-index: 5; background: #fff; border: 1px solid #ccc; border-top: none; border-radius: 0 0 4px 4px; max-height: 220px; overflow-y: auto; box-shadow: 0 4px 8px rgba(0,0,0,0.05); }}
.nc-provider-dropdown[hidden] {{ display: none; }}
.nc-provider-result {{ display: block; width: 100%; text-align: left; padding: 6px 10px; font-size: 12px; background: #fff; border: none; border-bottom: 1px solid #f0f0f0; cursor: pointer; font-family: inherit; }}
.nc-provider-result:hover {{ background: #e8f5e9; }}
.nc-provider-empty {{ padding: 8px 10px; font-size: 11px; color: #777; font-style: italic; }}
.nc-provider-chip {{ display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px; background: #e8f5e9; border: 1px solid #2e7d32; border-radius: 16px; font-size: 12px; max-width: 100%; }}
.nc-provider-chip[hidden] {{ display: none; }}
.nc-provider-chip-label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.nc-provider-chip-clear {{ background: transparent; border: none; color: #2e7d32; font-size: 14px; line-height: 1; cursor: pointer; padding: 0 2px; font-family: inherit; }}
.nc-provider-chip-clear:hover {{ color: #c62828; }}

.nc-manual-fallback {{ background: #fff; border: 1px solid #e0e0e0; border-radius: 4px; padding: 4px 10px; margin-top: 4px; }}
.nc-manual-fallback > summary {{ cursor: pointer; font-size: 11px; color: #555; padding: 4px 0; user-select: none; }}
.nc-manual-fallback[open] > summary {{ color: #2e7d32; padding-bottom: 8px; border-bottom: 1px dashed #e0e0e0; margin-bottom: 8px; }}
.nc-manual-fallback .nc-field {{ margin-top: 6px; }}

.nc-field-error > .nc-input,
.nc-field-error > .nc-textarea,
.nc-field-error > select.nc-input,
.nc-field-error > .nc-checklist,
.nc-field-error > .nc-provider-search > .nc-provider-input {{ border-color: #d32f2f !important; box-shadow: 0 0 0 2px rgba(211,47,47,0.12) !important; }}
.nc-field-error > .nc-label {{ color: #c62828; }}
.nc-field-error-msg {{ font-size: 11px; color: #c62828; font-weight: 500; margin-top: 2px; }}

.nc-meta {{ font-size: 11px; color: #777; margin-top: 16px; }}
.nc-meta code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<div class="nc-container">
  <div class="nc-header">
    <span class="nc-badge">{escape(safe_note_type)}</span>
    <span class="nc-visit-toggle">
      <label><input type="radio" name="visit_type" value="initial" checked> Initial</label>
      <label><input type="radio" name="visit_type" value="follow_up"> Follow-up</label>
    </span>
  </div>

  {sections_html}

  <div class="nc-meta">
    note_uuid: <code>{escape(note_uuid or "-")}</code> · patient_id: <code>{escape(patient_id or "-")}</code>
  </div>
</div>

<script>
(function() {{
  var NOTE_UUID = {note_uuid_js};
  var FLAT_SECTIONS = {flat_fields_js};
  var MULTI_SECTIONS = {multi_sections_js};
  var API = "/plugin-io/api/nutrition_charting";

  // Canvas embeds the tab in a srcdoc iframe whose container constrains its
  // height to ~150px by default. Reach into the parent document (srcdoc is
  // same-origin) and stretch the iframe element so the tab fills the note body.
  function expandHostIframe() {{
    try {{
      var parentDoc = window.parent && window.parent.document;
      if (!parentDoc) return;
      var iframes = parentDoc.querySelectorAll('iframe');
      for (var i = 0; i < iframes.length; i++) {{
        if (iframes[i].contentWindow === window) {{
          var iframe = iframes[i];
          iframe.style.minHeight = '80vh';
          iframe.style.height = '80vh';
          iframe.style.width = '100%';
          // Walk up a few ancestors and ensure none of them clip our height.
          var node = iframe.parentElement;
          for (var depth = 0; node && depth < 4; depth++) {{
            node.style.minHeight = '80vh';
            node = node.parentElement;
          }}
          return;
        }}
      }}
    }} catch (e) {{
      // Cross-origin or other failure — internal scroll handles overflow.
      console.warn('nc: host iframe expand failed', e && e.message);
    }}
  }}
  expandHostIframe();
  window.addEventListener('load', expandHostIframe);

  function $(id) {{ return document.getElementById(id); }}

  window.toggleSection = function(id) {{
    var section = $("section-" + id);
    if (!section) return;
    if (section.classList.contains("nc-section--expanded")) {{
      section.classList.remove("nc-section--expanded");
      section.classList.add("nc-section--collapsed");
    }} else {{
      section.classList.remove("nc-section--collapsed");
      section.classList.add("nc-section--expanded");
    }}
  }};

  function setStatus(id, message, kind) {{
    var el = $("save-status-" + id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "nc-status" + (kind ? " nc-status--" + kind : "");
  }}

  // Header-row status mirror: stays visible after auto-collapse so the
  // dietician sees the "Saved" / "Save failed" feedback even when the
  // section body is hidden.
  function setHeaderStatus(id, message, kind) {{
    var el = $("status-" + id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "nc-section-status" + (kind ? " nc-section-status--" + kind : "");
  }}

  // Canvas live-updates the host's Commands tab for ORIGINATE/EDIT effects
  // but not DELETE — show a one-click refresh link only when the save we
  // just made included a delete. `window.top.location.reload()` reloads the
  // whole note page; form-state is persisted server-side so saved data
  // survives.
  function setRefreshLinkVisible(id, visible) {{
    var link = $("refresh-link-" + id);
    if (!link) return;
    if (visible) link.removeAttribute("hidden");
    else link.setAttribute("hidden", "hidden");
  }}

  function expandSection(id) {{
    var section = $("section-" + id);
    if (!section) return;
    section.classList.remove("nc-section--collapsed");
    section.classList.add("nc-section--expanded");
  }}

  function collapseSection(id) {{
    var section = $("section-" + id);
    if (!section) return;
    section.classList.remove("nc-section--expanded");
    section.classList.add("nc-section--collapsed");
  }}

  // After auto-collapse, position the next section's header at the middle
  // of the iframe so the just-collapsed section stays visible right above
  // it. `block: "center"` aligns the *header* (not the whole section) at
  // viewport center — header in the middle, just-collapsed section above,
  // next section's body below.
  function scrollToNextSection(id) {{
    var section = $("section-" + id);
    if (!section) return;
    var next = section.nextElementSibling;
    while (next && !next.classList.contains("nc-section")) {{
      next = next.nextElementSibling;
    }}
    if (!next) return;
    var nextHeader = next.querySelector(".nc-section-header");
    if (!nextHeader) return;
    try {{
      nextHeader.scrollIntoView({{block: "center", behavior: "smooth"}});
    }} catch (e) {{
      // Older Safari without options support — fall back to the default.
      nextHeader.scrollIntoView();
    }}
  }}

  // Per spec §4.1: an Initial visit expands every section by default; a
  // Follow-up collapses the history-heavy ones (Medical Chart Review,
  // Social and Diet History, Dietary Intake) since they're reference data
  // for follow-ups, not the focus of the visit. Auto-populate still runs
  // either way — the form just opens tighter on follow-ups.
  var FOLLOW_UP_COLLAPSED_SECTIONS = [
    "medical_chart_review",
    "social_diet_history",
    "dietary_intake",
  ];

  function applyVisitTypeDefaults(visitType) {{
    var collapseSet = {{}};
    if (visitType === "follow_up") {{
      FOLLOW_UP_COLLAPSED_SECTIONS.forEach(function(id) {{ collapseSet[id] = true; }});
    }}
    var sections = document.querySelectorAll(".nc-section");
    for (var i = 0; i < sections.length; i++) {{
      var sec = sections[i];
      var id = (sec.id || "").replace(/^section-/, "");
      if (!id) continue;
      if (collapseSet[id]) {{
        sec.classList.remove("nc-section--expanded");
        sec.classList.add("nc-section--collapsed");
      }} else {{
        sec.classList.remove("nc-section--collapsed");
        sec.classList.add("nc-section--expanded");
      }}
    }}
  }}

  function recalcBmi() {{
    var hIn = parseFloat(($("height") || {{}}).value);
    var wLbs = parseFloat(($("weight") || {{}}).value);
    var bmiInput = $("bmi");
    if (!bmiInput) return;
    if (!isFinite(hIn) || hIn <= 0 || !isFinite(wLbs) || wLbs <= 0) {{
      bmiInput.value = "";
      return;
    }}
    var bmi = (wLbs / (hIn * hIn)) * 703;
    bmiInput.value = bmi.toFixed(1);
  }}

  ["height", "weight"].forEach(function(id) {{
    var el = $(id);
    if (el) el.addEventListener("input", recalcBmi);
  }});
  recalcBmi();

  function getVisitType() {{
    var radios = document.querySelectorAll('input[name="visit_type"]');
    for (var i = 0; i < radios.length; i++) {{
      if (radios[i].checked) return radios[i].value;
    }}
    return "initial";
  }}

  function setVisitType(value) {{
    if (!value) return;
    var radios = document.querySelectorAll('input[name="visit_type"]');
    for (var i = 0; i < radios.length; i++) {{
      radios[i].checked = (radios[i].value === value);
    }}
  }}

  function uuidv4() {{
    if (window.crypto && typeof window.crypto.randomUUID === "function") {{
      return window.crypto.randomUUID();
    }}
    // Fallback for older browsers — collision risk is negligible at our scale.
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {{
      var r = Math.random() * 16 | 0, v = c === "x" ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    }});
  }}

  function collectChecklistValues(fieldId) {{
    var inputs = document.querySelectorAll('[data-checklist-target="' + fieldId + '"]');
    var values = [];
    for (var i = 0; i < inputs.length; i++) {{
      if (inputs[i].checked) values.push(inputs[i].value);
    }}
    return values;
  }}

  function applyChecklistValues(fieldId, values) {{
    var set = {{}};
    (values || []).forEach(function(v) {{ set[v] = true; }});
    var inputs = document.querySelectorAll('[data-checklist-target="' + fieldId + '"]');
    for (var i = 0; i < inputs.length; i++) {{
      inputs[i].checked = !!set[inputs[i].value];
    }}
  }}

  function applyFieldValue(fieldId, kind, value) {{
    if (kind === "checklist") {{
      applyChecklistValues(fieldId, Array.isArray(value) ? value : []);
      return;
    }}
    var el = $(fieldId);
    if (!el) return;
    if (kind === "checkbox") {{
      el.checked = value === true || value === "true" || value === "on" || value === 1;
      return;
    }}
    if (value == null) {{
      el.value = "";
      return;
    }}
    el.value = value;
  }}

  function readFieldValue(fieldId, kind) {{
    if (kind === "checklist") {{
      return collectChecklistValues(fieldId);
    }}
    var el = $(fieldId);
    if (!el) return null;
    if (kind === "checkbox") return el.checked === true;
    var v = el.value;
    return v === "" ? null : v;
  }}

  function applySavedFlatSection(sectionId, data) {{
    if (!data || typeof data !== "object") return;
    var fields = FLAT_SECTIONS[sectionId] || [];
    fields.forEach(function(field) {{
      if (field.id in data) applyFieldValue(field.id, field.kind, data[field.id]);
    }});
    if (sectionId === "medical_chart_review") recalcBmi();
  }}

  function collectFlatSection(sectionId) {{
    var data = {{}};
    var fields = FLAT_SECTIONS[sectionId] || [];
    fields.forEach(function(field) {{
      data[field.id] = readFieldValue(field.id, field.kind);
    }});
    return data;
  }}

  // ---- Multi-command sections --------------------------------------------

  function rowsContainer(sectionId) {{
    return document.querySelector('[data-multi-section="' + sectionId + '"]');
  }}

  function buildMultiRow(sectionId, rowId, values) {{
    var descriptor = MULTI_SECTIONS[sectionId];
    if (!descriptor) return null;
    values = values || {{}};
    var wrapper = document.createElement("div");
    wrapper.className = "nc-multi-row";
    wrapper.setAttribute("data-row-id", rowId);

    descriptor.row_fields.forEach(function(field) {{
      var domId = sectionId + "__" + field.id + "__" + rowId;
      var fieldDiv = document.createElement("div");
      fieldDiv.className = "nc-field nc-field--full";

      // Hidden field: pure form-state carrier with no UI. Used today
      // for `service_provider_label` so the typeahead can restore the
      // selected-chip display on tab reload without a round-trip.
      if (field.kind === "hidden") {{
        var hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.id = domId;
        hidden.setAttribute("data-row-field", field.id);
        if (values[field.id] != null) hidden.value = values[field.id];
        wrapper.appendChild(hidden);
        return;
      }}

      // Provider-search typeahead: searches the instance's ServiceProvider
      // directory via /charting/refer-search. On select, stores the DB
      // record id in a hidden input (data-row-field="service_provider_id")
      // and the human label in a peer "service_provider_label" hidden
      // input the row already declared. Falls through to the four manual
      // provider_* text fields if the dietician doesn't pick from the
      // dropdown — those are evaluated server-side only when the id is
      // empty.
      if (field.kind === "provider_search") {{
        var labelEl = document.createElement("label");
        labelEl.className = "nc-label";
        labelEl.textContent = field.label;
        fieldDiv.appendChild(labelEl);

        var idInput = document.createElement("input");
        idInput.type = "hidden";
        idInput.id = domId;
        idInput.setAttribute("data-row-field", field.id);
        if (values[field.id] != null) idInput.value = values[field.id];
        fieldDiv.appendChild(idInput);

        var box = document.createElement("div");
        box.className = "nc-provider-search";

        var chip = document.createElement("div");
        chip.className = "nc-provider-chip";
        chip.setAttribute("hidden", "hidden");
        var chipLabel = document.createElement("span");
        chipLabel.className = "nc-provider-chip-label";
        var chipClear = document.createElement("button");
        chipClear.type = "button";
        chipClear.className = "nc-provider-chip-clear";
        chipClear.textContent = "×";
        chipClear.setAttribute("aria-label", "Clear selected provider");
        chip.appendChild(chipLabel);
        chip.appendChild(chipClear);

        var searchInput = document.createElement("input");
        searchInput.type = "text";
        searchInput.className = "nc-input nc-provider-input";
        searchInput.setAttribute("placeholder", "Search by name or practice…");
        searchInput.setAttribute("autocomplete", "off");

        var dropdown = document.createElement("div");
        dropdown.className = "nc-provider-dropdown";
        dropdown.setAttribute("hidden", "hidden");

        function setSelected(id, label) {{
          idInput.value = id || "";
          var labelInput = wrapper.querySelector(
            '[data-row-field="service_provider_label"]'
          );
          if (labelInput) labelInput.value = label || "";
          if (id) {{
            chipLabel.textContent = label || id;
            chip.removeAttribute("hidden");
            searchInput.setAttribute("hidden", "hidden");
            dropdown.setAttribute("hidden", "hidden");
            searchInput.value = "";
          }} else {{
            chip.setAttribute("hidden", "hidden");
            searchInput.removeAttribute("hidden");
          }}
        }}

        chipClear.addEventListener("click", function() {{ setSelected("", ""); }});

        // Restore the chip on tab reload when both id and label are saved.
        var savedId = values[field.id];
        var savedLabel = values["service_provider_label"];
        if (savedId) {{
          setSelected(String(savedId), savedLabel ? String(savedLabel) : String(savedId));
        }}

        var searchToken = 0;
        var searchTimer = null;

        function renderResults(items) {{
          dropdown.innerHTML = "";
          if (!items || !items.length) {{
            var empty = document.createElement("div");
            empty.className = "nc-provider-empty";
            empty.textContent = "No matches — fill in the manual fields below to enter ad-hoc.";
            dropdown.appendChild(empty);
          }} else {{
            items.forEach(function(item) {{
              var row = document.createElement("button");
              row.type = "button";
              row.className = "nc-provider-result";
              row.textContent = item.label || (item.first_name + " " + item.last_name);
              row.addEventListener("click", function() {{
                setSelected(item.id, item.label || (item.first_name + " " + item.last_name));
              }});
              dropdown.appendChild(row);
            }});
          }}
          dropdown.removeAttribute("hidden");
        }}

        function runSearch(q) {{
          searchToken++;
          var token = searchToken;
          fetch(API + "/charting/refer-search?q=" + encodeURIComponent(q), {{
            credentials: "same-origin",
          }})
          .then(function(r) {{ return r.ok ? r.json() : {{success: false}}; }})
          .then(function(payload) {{
            if (token !== searchToken) return;  // stale response
            if (!payload || !payload.success) {{ renderResults([]); return; }}
            renderResults(payload.results || []);
          }})
          .catch(function() {{ if (token === searchToken) renderResults([]); }});
        }}

        searchInput.addEventListener("input", function() {{
          var q = (searchInput.value || "").trim();
          if (searchTimer) {{ clearTimeout(searchTimer); }}
          if (q.length < 2) {{
            dropdown.setAttribute("hidden", "hidden");
            return;
          }}
          searchTimer = setTimeout(function() {{ runSearch(q); }}, 200);
        }});

        searchInput.addEventListener("blur", function() {{
          // Delay so a click on a result still fires before the dropdown hides.
          setTimeout(function() {{ dropdown.setAttribute("hidden", "hidden"); }}, 150);
        }});

        box.appendChild(chip);
        box.appendChild(searchInput);
        box.appendChild(dropdown);
        fieldDiv.appendChild(box);
        wrapper.appendChild(fieldDiv);
        return;
      }}

      // Checkbox: label wraps the input on a single line (matches the
      // single-command checkbox renderer's affordance).
      if (field.kind === "checkbox") {{
        var cbLabel = document.createElement("label");
        cbLabel.className = "nc-checkbox";
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.id = domId;
        cb.setAttribute("data-row-field", field.id);
        cb.setAttribute("data-row-field-kind", "checkbox");
        var v = values[field.id];
        cb.checked = (v === true || v === "true" || v === "on" || v === 1);
        var cbText = document.createElement("span");
        cbText.textContent = " " + field.label;
        cbLabel.appendChild(cb);
        cbLabel.appendChild(cbText);
        fieldDiv.appendChild(cbLabel);
        wrapper.appendChild(fieldDiv);
        return;
      }}

      var label = document.createElement("label");
      label.className = "nc-label";
      label.setAttribute("for", domId);
      label.textContent = field.label;
      fieldDiv.appendChild(label);

      // Multiselect renders as a checklist of canonical options (e.g. the
      // patient's active PMH for indications). The container itself
      // carries the data-row-field marker so collectMultiSection can find
      // it and roll up the checked values into a list[str].
      if (field.kind === "multiselect") {{
        var msOpts = field.options || [];
        var saved = Array.isArray(values[field.id]) ? values[field.id] : [];
        var savedSet = {{}};
        saved.forEach(function(v) {{ savedSet[v] = true; }});
        // Track which option values appear in the canonical option list
        // (current active PMH for the referrals row's "indications"
        // field). Saved values absent from msOpts are "ghost" entries
        // — codes that were active when the dietician originally
        // selected them but whose underlying chart entry has since
        // been retracted (entered_in_error) or resolved. Without
        // explicit handling, those codes have no DOM checkbox, so
        // collectMultiSection silently drops them on the next save —
        // corrupting the committed Refer command's diagnosis_codes
        // (or deleting the whole command if all indications drop).
        // Render them as checked "(no longer active)" checkboxes so
        // the dietician sees what's on the row and can deliberately
        // uncheck to remove; otherwise the collector rolls the value
        // back up unchanged.
        var optsSet = {{}};
        msOpts.forEach(function(opt) {{ optsSet[opt.value] = true; }});
        var msContainer = document.createElement("div");
        msContainer.className = "nc-checklist nc-multiselect";
        msContainer.setAttribute("data-row-field", field.id);
        msContainer.setAttribute("data-row-field-kind", "multiselect");
        if (msOpts.length === 0 && saved.length === 0) {{
          var empty = document.createElement("p");
          empty.className = "nc-empty";
          empty.textContent = "No active conditions on record.";
          msContainer.appendChild(empty);
        }} else {{
          msOpts.forEach(function(opt) {{
            var optLabel = document.createElement("label");
            optLabel.className = "nc-checkbox nc-checkbox--inline";
            var optCb = document.createElement("input");
            optCb.type = "checkbox";
            optCb.value = opt.value;
            optCb.checked = !!savedSet[opt.value];
            var optSpan = document.createElement("span");
            optSpan.textContent = " " + opt.label;
            optLabel.appendChild(optCb);
            optLabel.appendChild(optSpan);
            msContainer.appendChild(optLabel);
          }});
          saved.forEach(function(v) {{
            if (!v || optsSet[v]) return;
            var ghostLabel = document.createElement("label");
            ghostLabel.className =
              "nc-checkbox nc-checkbox--inline nc-checkbox--ghost";
            var ghostCb = document.createElement("input");
            ghostCb.type = "checkbox";
            ghostCb.value = v;
            ghostCb.checked = true;
            var ghostSpan = document.createElement("span");
            ghostSpan.textContent = " " + v + " (no longer active)";
            ghostLabel.appendChild(ghostCb);
            ghostLabel.appendChild(ghostSpan);
            msContainer.appendChild(ghostLabel);
          }});
        }}
        fieldDiv.appendChild(msContainer);
        wrapper.appendChild(fieldDiv);
        return;
      }}

      var input;
      if (field.kind === "textarea") {{
        input = document.createElement("textarea");
        input.rows = 2;
        input.className = "nc-input nc-textarea";
      }} else if (field.kind === "select") {{
        input = document.createElement("select");
        input.className = "nc-input";
        var opts = field.options || [];
        for (var k = 0; k < opts.length; k++) {{
          var o = document.createElement("option");
          o.value = opts[k].value;
          o.textContent = opts[k].label;
          input.appendChild(o);
        }}
      }} else {{
        input = document.createElement("input");
        input.type = "text";
        input.className = "nc-input";
      }}
      input.id = domId;
      input.setAttribute("data-row-field", field.id);
      if (values[field.id] != null) input.value = values[field.id];
      fieldDiv.appendChild(input);
      wrapper.appendChild(fieldDiv);
    }});

    var canonical = String(rowId).indexOf(descriptor.row_id_prefix + ":") === 0;
    if (!canonical) {{
      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "nc-remove-row-btn";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", function() {{ wrapper.remove(); }});
      wrapper.appendChild(removeBtn);
    }} else {{
      // Canonical rows are managed via the checklist toggle, not Remove.
      wrapper.setAttribute("data-canonical", "true");
    }}

    // Referrals: tuck the four manual provider_* fields under a
    // default-collapsed <details>. The typeahead at the top is the
    // primary affordance; manual entry stays accessible but doesn't
    // crowd out the required fields below.
    if (sectionId === "referrals") {{
      var manualInputs = wrapper.querySelectorAll(
        '[data-row-field^="provider_"]'
      );
      if (manualInputs.length) {{
        var details = document.createElement("details");
        details.className = "nc-manual-fallback";
        var summary = document.createElement("summary");
        summary.textContent = "Provider not in directory? Type manually ↓";
        details.appendChild(summary);
        var manualWasFilled = false;
        for (var mi = 0; mi < manualInputs.length; mi++) {{
          var manualInput = manualInputs[mi];
          if (manualInput.value && String(manualInput.value).trim()) {{
            manualWasFilled = true;
          }}
          var manualFieldDiv = manualInput.closest(".nc-field");
          if (manualFieldDiv) details.appendChild(manualFieldDiv);
        }}
        // Auto-expand if any manual field had a saved value (form-state restore).
        if (manualWasFilled) details.setAttribute("open", "open");
        var indicationsInput = wrapper.querySelector(
          '[data-row-field="indications"]'
        );
        if (indicationsInput) {{
          var indicationsDiv = indicationsInput.closest(".nc-field");
          if (indicationsDiv) {{
            wrapper.insertBefore(details, indicationsDiv);
          }} else {{
            wrapper.appendChild(details);
          }}
        }} else {{
          wrapper.appendChild(details);
        }}
      }}
    }}

    return wrapper;
  }}

  function findRow(sectionId, rowId) {{
    var container = rowsContainer(sectionId);
    if (!container) return null;
    return container.querySelector('[data-row-id="' + rowId + '"]');
  }}

  function ensureRow(sectionId, rowId, values) {{
    var existing = findRow(sectionId, rowId);
    if (existing) return existing;
    var container = rowsContainer(sectionId);
    if (!container) return null;
    var row = buildMultiRow(sectionId, rowId, values);
    if (row) container.appendChild(row);
    return row;
  }}

  function removeRow(sectionId, rowId) {{
    var existing = findRow(sectionId, rowId);
    if (existing) existing.remove();
  }}

  function applySavedMultiSection(sectionId, data) {{
    if (!data || typeof data !== "object") return;
    var rows = Array.isArray(data.rows) ? data.rows : [];
    var descriptor = MULTI_SECTIONS[sectionId];
    rows.forEach(function(row) {{
      if (!row || !row.row_id) return;
      var values = {{}};
      (descriptor.row_fields || []).forEach(function(field) {{
        if (row[field.id] != null) values[field.id] = row[field.id];
      }});
      ensureRow(sectionId, row.row_id, values);
      // If this row corresponds to a canonical checklist option, reflect it.
      var canonicalCheckbox = document.querySelector(
        '[data-multi-canonical="' + sectionId + '"][data-row-id="' + row.row_id + '"]'
      );
      if (canonicalCheckbox) canonicalCheckbox.checked = true;
    }});
  }}

  function collectMultiSection(sectionId) {{
    var descriptor = MULTI_SECTIONS[sectionId];
    if (!descriptor) return {{rows: []}};
    var container = rowsContainer(sectionId);
    var rows = [];
    if (container) {{
      var rowEls = container.querySelectorAll(".nc-multi-row");
      for (var i = 0; i < rowEls.length; i++) {{
        var rowEl = rowEls[i];
        var rowId = rowEl.getAttribute("data-row-id");
        if (!rowId) continue;
        var rowData = {{row_id: rowId}};
        var inputs = rowEl.querySelectorAll("[data-row-field]");
        for (var j = 0; j < inputs.length; j++) {{
          var inputEl = inputs[j];
          var fieldId = inputEl.getAttribute("data-row-field");
          var fieldKind = inputEl.getAttribute("data-row-field-kind");
          if (fieldKind === "checkbox") {{
            // Read .checked, not .value (always "on" regardless of state).
            rowData[fieldId] = inputEl.checked === true;
          }} else if (fieldKind === "multiselect") {{
            // Collect every checked checkbox value into a list[str].
            var msChecked = inputEl.querySelectorAll("input[type=checkbox]");
            var msVals = [];
            for (var k = 0; k < msChecked.length; k++) {{
              if (msChecked[k].checked) msVals.push(msChecked[k].value);
            }}
            rowData[fieldId] = msVals;
          }} else {{
            rowData[fieldId] = inputEl.value;
          }}
        }}
        rows.push(rowData);
      }}
    }}
    return {{rows: rows}};
  }}

  function loadFormState() {{
    if (!NOTE_UUID) {{
      // Even with no note context we still want the Initial-vs-Follow-up
      // defaults to apply against whatever the radio shows.
      applyVisitTypeDefaults(getVisitType());
      return;
    }}
    fetch(API + "/charting/form-state?note_id=" + encodeURIComponent(NOTE_UUID), {{
      credentials: "same-origin",
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(payload) {{
      if (!payload || !payload.success) return;
      if (payload.visit_type) setVisitType(payload.visit_type);
      var saved = (payload.sections || {{}});
      Object.keys(FLAT_SECTIONS).forEach(function(sectionId) {{
        if (saved[sectionId]) applySavedFlatSection(sectionId, saved[sectionId]);
      }});
      Object.keys(MULTI_SECTIONS).forEach(function(sectionId) {{
        if (saved[sectionId]) applySavedMultiSection(sectionId, saved[sectionId]);
      }});
      // Apply visit-type expand/collapse defaults AFTER form-state loads
      // so the saved visit_type wins over the radio's default value.
      applyVisitTypeDefaults(getVisitType());
    }})
    .catch(function(err) {{
      console.warn("nc: form-state load failed", err);
      applyVisitTypeDefaults(getVisitType());
    }});
  }}

  function collectSection(sectionId) {{
    if (MULTI_SECTIONS[sectionId]) return collectMultiSection(sectionId);
    return collectFlatSection(sectionId);
  }}

  function clearRowFieldError(fieldDiv) {{
    if (!fieldDiv) return;
    fieldDiv.classList.remove("nc-field-error");
    var msg = fieldDiv.querySelector(".nc-field-error-msg");
    if (msg) msg.remove();
  }}

  function markRowFieldError(fieldDiv) {{
    if (!fieldDiv) return;
    if (!fieldDiv.classList.contains("nc-field-error")) {{
      fieldDiv.classList.add("nc-field-error");
      var msg = document.createElement("div");
      msg.className = "nc-field-error-msg";
      msg.textContent = "Required";
      fieldDiv.appendChild(msg);
    }}
    // Clear the error as soon as the user touches the field.
    fieldDiv.querySelectorAll("input, textarea, select").forEach(function(el) {{
      var clear = function() {{ clearRowFieldError(fieldDiv); }};
      el.addEventListener("input", clear, {{once: true}});
      el.addEventListener("change", clear, {{once: true}});
    }});
  }}

  // Per-row required-field check for multi-command sections. Returns an
  // array of error strings (empty == valid). Marks each offending field's
  // .nc-field container with .nc-field-error so the dietician sees what's
  // missing before clicking Save again.
  function validateMultiSection(sectionId) {{
    var descriptor = MULTI_SECTIONS[sectionId];
    if (!descriptor) return [];
    var requiredFields = descriptor.required_fields || [];
    if (!requiredFields.length) return [];
    var requiredLabels = {{}};
    (descriptor.row_fields || []).forEach(function(field) {{
      requiredLabels[field.id] = (field.label || field.id).replace(/\\s*\\*\\s*$/, "");
    }});

    var container = rowsContainer(sectionId);
    if (!container) return [];
    var errors = [];
    var rowEls = container.querySelectorAll(".nc-multi-row");
    for (var i = 0; i < rowEls.length; i++) {{
      var rowEl = rowEls[i];
      for (var j = 0; j < requiredFields.length; j++) {{
        var fieldId = requiredFields[j];
        var inputEl = rowEl.querySelector('[data-row-field="' + fieldId + '"]');
        if (!inputEl) continue;
        var fieldKind = inputEl.getAttribute("data-row-field-kind");
        var filled = false;
        if (fieldKind === "checkbox") {{
          filled = inputEl.checked === true;
        }} else if (fieldKind === "multiselect") {{
          var checks = inputEl.querySelectorAll("input[type=checkbox]");
          for (var k = 0; k < checks.length; k++) {{
            if (checks[k].checked) {{ filled = true; break; }}
          }}
        }} else {{
          filled = !!(inputEl.value && String(inputEl.value).trim());
        }}
        if (!filled) {{
          var fieldDiv = inputEl.closest(".nc-field") || inputEl.parentElement;
          markRowFieldError(fieldDiv);
          errors.push(requiredLabels[fieldId] || fieldId);
        }}
      }}
    }}
    return errors;
  }}

  function save(sectionId) {{
    if (!NOTE_UUID) {{
      setStatus(sectionId, "Cannot save — no note context", "error");
      return;
    }}

    // Client-side gate: multi-command sections with required_fields refuse
    // to submit until every row has all asterisked fields filled. Mirrors
    // the server's `is_row_ready` check so a row that would be silently
    // skipped server-side gets blocked before it leaves the browser.
    if (MULTI_SECTIONS[sectionId]) {{
      var missing = validateMultiSection(sectionId);
      if (missing.length) {{
        // De-duplicate and join the missing-field labels for the status line.
        var seen = {{}};
        var labels = [];
        missing.forEach(function(m) {{
          if (!seen[m]) {{ seen[m] = true; labels.push(m); }}
        }});
        setStatus(sectionId, "Required: " + labels.join(", "), "error");
        setHeaderStatus(sectionId, "Required fields missing", "error");
        return;
      }}
    }}

    var btn = document.querySelector('[data-save-section="' + sectionId + '"]');
    if (btn) btn.disabled = true;
    setStatus(sectionId, "Saving…", "saving");
    setHeaderStatus(sectionId, "", null);
    // Hide any stale refresh prompt from a prior save while this one is in flight.
    setRefreshLinkVisible(sectionId, false);

    var body = collectSection(sectionId);
    body.visit_type = getVisitType();

    var url = API + "/charting/save?section=" + encodeURIComponent(sectionId)
      + "&note_id=" + encodeURIComponent(NOTE_UUID);
    fetch(url, {{
      method: "POST",
      credentials: "same-origin",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify(body),
    }})
    .then(function(r) {{ return r.json().then(function(j) {{ return [r.ok, j]; }}); }})
    .then(function(arr) {{
      var ok = arr[0]; var j = arr[1];
      if (ok && j && j.success) {{
        setStatus(sectionId, "Saved", "saved");
        setHeaderStatus(sectionId, "Saved", "saved");
        var deleteCount = j.effects && typeof j.effects.delete === "number"
          ? j.effects.delete : 0;
        if (deleteCount > 0) {{
          // Keep the section expanded so the "↻ Refresh to see changes"
          // link stays visible — the dietician needs to see + click it.
          setRefreshLinkVisible(sectionId, true);
        }} else {{
          // Clean save: auto-collapse so the form stays tight as the
          // dietician moves through the ADIME flow. The "Saved" status
          // mirrored to the section header keeps the feedback visible.
          collapseSection(sectionId);
          // Slide the next section into the middle of the iframe so the
          // just-collapsed section stays visible right above it.
          scrollToNextSection(sectionId);
        }}
      }} else {{
        setStatus(sectionId, "Save failed", "error");
        setHeaderStatus(sectionId, "Save failed", "error");
        console.error("nc: save error", j);
      }}
    }})
    .catch(function(err) {{
      setStatus(sectionId, "Save failed", "error");
      setHeaderStatus(sectionId, "Save failed", "error");
      console.error("nc: save fetch failed", err);
    }})
    .then(function() {{
      if (btn) btn.disabled = false;
    }});
  }}

  document.querySelectorAll('[data-save-section]').forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      save(btn.getAttribute("data-save-section"));
    }});
  }});

  // Refresh-after-delete affordance: reload the whole note page (not just
  // our iframe) so the host's Commands tab re-fetches and the deleted
  // command actually disappears.
  document.querySelectorAll('[data-refresh-link]').forEach(function(link) {{
    link.addEventListener("click", function(e) {{
      e.preventDefault();
      try {{ window.top.location.reload(); }}
      catch (err) {{ window.location.reload(); }}
    }});
  }});

  // "+ Add another" buttons mint a fresh row_id and inject an empty row.
  document.querySelectorAll('[data-add-row]').forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      var sectionId = btn.getAttribute("data-add-row");
      var descriptor = MULTI_SECTIONS[sectionId];
      if (!descriptor) return;
      var rowId = (descriptor.row_id_prefix || sectionId) + ":" + uuidv4();
      ensureRow(sectionId, rowId, {{}});
    }});
  }});

  // Canonical checklist (educational materials): toggling a checkbox adds or
  // removes the corresponding canonical row. The data-row-id stays stable so
  // re-checking after an unsave doesn't mint a duplicate command.
  document.querySelectorAll('[data-multi-canonical]').forEach(function(input) {{
    input.addEventListener("change", function() {{
      var sectionId = input.getAttribute("data-multi-canonical");
      var rowId = input.getAttribute("data-row-id");
      var name = input.getAttribute("data-name") || "";
      if (!sectionId || !rowId) return;
      if (input.checked) {{
        ensureRow(sectionId, rowId, {{name: name}});
      }} else {{
        removeRow(sectionId, rowId);
      }}
    }});
  }});

  // Toggling Initial / Follow-up reapplies the section expand/collapse
  // defaults from spec §4.1. Per-section collapse state isn't persisted,
  // so the dietician can still manually expand any section after the
  // radio change.
  document.querySelectorAll('input[name="visit_type"]').forEach(function(radio) {{
    radio.addEventListener("change", function() {{
      if (radio.checked) applyVisitTypeDefaults(radio.value);
    }});
  }});

  loadFormState();
}})();
</script>
</body>
</html>"""
