"""Render summary HTML from structured data. No LLM output touches HTML structure."""
from __future__ import annotations


def _esc(value: str) -> str:
    """HTML-escape a string for safe insertion into templates."""
    s = str(value)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&#x27;")
    return s


COMMAND_LABELS: dict[str, str] = {
    "reasonForVisit": "Reason for Visit",
    "hpi": "HPI",
    "assess": "Assess",
    "diagnose": "Diagnose",
    "updateDiagnosis": "Update Diagnosis",
    "resolveCondition": "Resolve Condition",
    "plan": "Plan",
    "instruct": "Instructions",
    "followUp": "Follow Up",
    "follow_up": "Follow Up",
    "prescribe": "Prescribe",
    "medicationStatement": "Med Statement",
    "medication_statement": "Med Statement",
    "stopMedication": "Stop Medication",
    "refill": "Refill",
    "refer": "Referral",
    "labOrder": "Lab Order",
    "imagingOrder": "Imaging Order",
    "allergy": "Allergy",
    "immunize": "Immunization",
    "immunizationStatement": "Immunization Statement",
    "vitals": "Vitals",
    "questionnaire": "Questionnaire",
}


COMMAND_SECTION_COLORS: dict[str, str] = {
    "reasonForVisit": "#000000",
    "hpi": "#000000",
    "questionnaire": "#000000",
    "vitals": "#23b135",
    "assess": "#ed4b0a",
    "diagnose": "#ed4b0a",
    "updateDiagnosis": "#ed4b0a",
    "resolveCondition": "#ed4b0a",
    "plan": "#1d6fc5",
    "instruct": "#1d6fc5",
    "followUp": "#1d6fc5",
    "prescribe": "#1d6fc5",
    "refill": "#1d6fc5",
    "stopMedication": "#1d6fc5",
    "refer": "#1d6fc5",
    "labOrder": "#1d6fc5",
    "imagingOrder": "#1d6fc5",
    "immunize": "#5019be",
    "allergy": "#935330",
    "immunizationStatement": "#935330",
    "medicationStatement": "#935330",
}


def _section_remove_btn() -> str:
    """Render a section-level remove button (visible only in edit mode)."""
    return (
        '<button class="section-remove" aria-label="Remove section">'
        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none">'
        '<path d="M2 2L10 10M10 2L2 10" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round"/>'
        '</svg></button>'
    )


def _item_remove_btn() -> str:
    """Render a standalone item remove button (no badge, edit mode only)."""
    return (
        '<button class="item-remove" aria-label="Remove">'
        '<svg width="12" height="12" viewBox="0 0 12 12" fill="none">'
        '<path d="M2 2L10 10M10 2L2 10" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round"/>'
        '</svg></button>'
    )


def _command_badge(schema_key: str) -> str:
    """Render a colored provenance badge with a remove button."""
    label = COMMAND_LABELS.get(schema_key, schema_key)
    color = COMMAND_SECTION_COLORS.get(schema_key, "#1d6fc5")
    return (
        f'<span class="avs-provenance">'
        f'<span class="cmd-badge" style="background:{color}">{_esc(label)}</span>'
        f'<button class="item-remove" aria-label="Remove">'
        f'<svg width="12" height="12" viewBox="0 0 12 12" fill="none">'
        f'<path d="M2 2L10 10M10 2L2 10" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
        f'</svg></button>'
        f'</span>'
    )


def _render_list(items: list[str], empty_msg: str = "None documented", removable: bool = False) -> str:
    if not items:
        return f'<p class="no-data">{_esc(empty_msg)}</p>'
    rm = _item_remove_btn() if removable else ""
    li = "".join(
        f'<li><span class="avs-item-text">{_esc(item)}</span>{rm}</li>'
        for item in items
    )
    return f"<ul>{li}</ul>"


def _render_vitals(vitals: dict[str, str | None]) -> str:
    """Render vitals as a compact two-column table without borders."""
    labels: dict[str, tuple[str, str]] = {
        "systolic": ("BP", " mmHg"),
        "heart_rate": ("HR", " bpm"),
        "spo2": ("SpO2", "%"),
        "temperature": ("Temp", " F"),
        "height": ("Height", " in"),
        "weight": ("Weight", " lbs"),
        "bmi": ("BMI", ""),
    }
    rows: list[tuple[str, str]] = []
    for key, (label, suffix) in labels.items():
        if key == "systolic":
            if vitals.get("systolic"):
                bp_val = f"{vitals['systolic']}/{vitals.get('diastolic', '?')}{suffix}"
                rows.append((label, bp_val))
            continue
        val = vitals.get(key)
        if val:
            rows.append((label, f"{val}{suffix}"))
    if not rows:
        return '<p class="no-data">No vitals documented</p>'
    table_rows = []
    for label, value in rows:
        table_rows.append(
            f'<tr><td class="vitals-label">{_esc(label)}</td>'
            f'<td class="vitals-value">{_esc(value)}</td></tr>'
        )
    return f'<table class="vitals-table" aria-label="Vitals snapshot">{"".join(table_rows)}</table>'


def render_previous_visit(
    llm_data: dict,
    chief_complaint: str,
    diagnoses: list[dict[str, str]],
    medications: list[dict[str, str]],
    plan_items: list,
    vitals: dict[str, str | None],
) -> str:
    """Render Previous Visit Summary HTML from extracted data and LLM phrasing."""
    sections = []

    # Chief complaint
    cc_text = llm_data.get("chief_complaint", "") or chief_complaint or "Not documented"
    sections.append(
        f'<div class="summary-section"><h3>Chief Complaint</h3>'
        f'<p>{_esc(cc_text)}</p></div>'
    )

    # Diagnoses
    dx_phrases = llm_data.get("diagnoses", [])
    if diagnoses:
        dx_items = []
        for i, dx in enumerate(diagnoses):
            code = dx.get("code", "")
            display = dx.get("display", "")
            tag = dx.get("tag", "")
            detail = dx_phrases[i] if i < len(dx_phrases) else ""
            code_str = f"<strong>{_esc(code)}</strong> - " if code else ""
            tag_str = f' <span class="badge">{_esc(tag)}</span>' if tag else ""
            detail_str = f": {_esc(detail)}" if detail else ""
            dx_items.append(f"<li>{code_str}{_esc(display)}{tag_str}{detail_str}</li>")
        dx_html = f'<ul>{"".join(dx_items)}</ul>'
    else:
        dx_html = '<p class="no-data">None documented</p>'
    sections.append(
        f'<div class="summary-section"><h3>Key Diagnoses Assessed</h3>{dx_html}</div>'
    )

    # Medications
    if medications:
        med_items = []
        for med in medications:
            name = med.get("name", "")
            dose = med.get("dose", "")
            sig = med.get("sig", "")
            status = med.get("status", "")
            name_dose = f"{name} {dose}".strip()
            sig_str = f" - {_esc(sig)}" if sig else ""
            status_str = f' <span class="badge">{_esc(status)}</span>' if status else ""
            med_items.append(f"<li><strong>{_esc(name_dose)}</strong>{status_str}{sig_str}</li>")
        med_html = f'<ul>{"".join(med_items)}</ul>'
    else:
        med_html = '<p class="no-data">None documented</p>'
    sections.append(
        f'<div class="summary-section"><h3>Medications Discussed</h3>{med_html}</div>'
    )

    # Plan
    plan_phrases = llm_data.get("plan_items", [])
    if plan_phrases:
        plan_display = plan_phrases
    else:
        plan_display = [item["text"] if isinstance(item, dict) else str(item) for item in plan_items]
    sections.append(
        f'<div class="summary-section"><h3>Plan &amp; Follow-up Items</h3>'
        f'{_render_list(plan_display)}</div>'
    )

    # Vitals
    sections.append(
        f'<div class="summary-section vitals-section"><h3>Vitals Snapshot</h3>'
        f'{_render_vitals(vitals)}</div>'
    )

    return "\n".join(sections)


def render_since_last_visit(
    llm_data: dict,
    lab_reports: list[dict],
    medication_changes: dict[str, list],
    condition_changes: dict[str, list],
    completed_tasks: list[str],
    other_encounters: list[str],
) -> str:
    """Render Since Last Visit Summary HTML from extracted data and LLM phrasing."""
    sections = []

    # Lab results
    lab_interpretation = llm_data.get("lab_interpretation", "")
    if lab_reports:
        rows = []
        for lab in lab_reports:
            name = _esc(lab.get("name", ""))
            value = _esc(lab.get("value", ""))
            units = _esc(lab.get("units", ""))
            ref = _esc(lab.get("reference_range", ""))
            flag = lab.get("flag", "")
            flag_html = f' <span class="lab-flag">[{_esc(flag)}]</span>' if flag else ""
            ref_html = f" (ref: {ref})" if ref else ""
            rows.append(f"<li><strong>{name}</strong>: {value} {units}{ref_html}{flag_html}</li>")
        lab_html = f'<ul>{"".join(rows)}</ul>'
        if lab_interpretation:
            lab_html += f'<div class="banner banner-warning"><div class="banner-header">Trend</div><p>{_esc(lab_interpretation)}</p></div>'
    else:
        lab_html = '<p class="no-data">No lab results in this period.</p>'
    sections.append(f'<div class="summary-section"><h3>Lab Results</h3>{lab_html}</div>')

    # Medication changes
    new_meds = medication_changes.get("new", [])
    stopped_meds = medication_changes.get("stopped", [])
    if new_meds or stopped_meds:
        med_items = []
        for m in new_meds:
            med_items.append(f"<li><strong>NEW:</strong> {_esc(m)}</li>")
        for m in stopped_meds:
            med_items.append(f"<li><strong>STOPPED:</strong> {_esc(m)}</li>")
        med_html = f'<ul>{"".join(med_items)}</ul>'
    else:
        med_html = '<p class="no-data">No medication changes.</p>'
    sections.append(f'<div class="summary-section"><h3>Medication Changes</h3>{med_html}</div>')

    # Condition changes
    new_conds = condition_changes.get("new", [])
    resolved_conds = condition_changes.get("resolved", [])
    if new_conds or resolved_conds:
        cond_items = []
        for c in new_conds:
            cond_items.append(f"<li><strong>NEW:</strong> {_esc(c)}</li>")
        for c in resolved_conds:
            cond_items.append(f"<li><strong>RESOLVED:</strong> {_esc(c)}</li>")
        cond_html = f'<ul>{"".join(cond_items)}</ul>'
    else:
        cond_html = '<p class="no-data">None.</p>'
    sections.append(f'<div class="summary-section"><h3>New Diagnoses</h3>{cond_html}</div>')

    # Completed tasks
    sections.append(
        f'<div class="summary-section"><h3>Completed Care Tasks</h3>'
        f'{_render_list(completed_tasks, "None.")}</div>'
    )

    # Other encounters
    sections.append(
        f'<div class="summary-section"><h3>Other Encounters</h3>'
        f'{_render_list(other_encounters, "None.")}</div>'
    )

    return "\n".join(sections)


def render_avs(
    llm_data: dict,
    patient_info: dict,
    medications: list[dict[str, str]],
    plan_items: list,
) -> str:
    """Render After Visit Summary HTML from extracted data and LLM phrasing."""
    first_name = _esc(patient_info.get("first_name", "Patient"))
    last_name = _esc(patient_info.get("last_name", ""))
    visit_date = _esc(patient_info.get("visit_date", "today"))
    provider = _esc(patient_info.get("provider_name", "your provider"))

    sections = []

    # Greeting
    xbtn = _section_remove_btn()
    sections.append(
        f'<div class="banner banner-info avs-removable" data-section="greeting">'
        f'<div class="avs-section-header">'
        f'<p style="flex:1">Hi {first_name},</p>{xbtn}</div>'
        f'<p>Thank you for visiting us on {visit_date}. '
        f'Here is a summary of your visit with {provider}.</p>'
        f'</div>'
    )

    # Discussion (LLM generated)
    discussion = llm_data.get("discussion", "We reviewed your health and discussed your care plan.")
    sections.append(
        f'<div class="avs-section avs-removable" data-section="discussion">'
        f'<div class="avs-section-header">'
        f'<h3>What We Discussed Today</h3>{xbtn}</div>'
        f'<p>{_esc(discussion)}</p></div>'
    )

    # Medications (deterministic structure, LLM rewrites instructions)
    med_phrases = llm_data.get("medications", [])
    if medications:
        med_items = []
        for i, med in enumerate(medications):
            name = med.get("name", "")
            dose = med.get("dose", "")
            schema_key = med.get("schema_key", "")
            name_dose = f"{name} {dose}".strip()
            instructions = med_phrases[i] if i < len(med_phrases) else med.get("sig", "")
            instr_str = f": {_esc(instructions)}" if instructions else ""
            cmd_badge = _command_badge(schema_key) if schema_key else _item_remove_btn()
            med_items.append(
                f'<li><span class="avs-item-text"><strong>{_esc(name_dose)}</strong>{instr_str}</span>{cmd_badge}</li>'
            )
        med_html = f'<ul>{"".join(med_items)}</ul>'
    else:
        med_html = "<p>No changes to your medications.</p>"
    sections.append(
        f'<div class="avs-section avs-removable" data-section="medications">'
        f'<div class="avs-section-header">'
        f'<h3>Your Medications</h3>{xbtn}</div>{med_html}</div>'
    )

    # Next steps (LLM rewrites plan items, badges show source command)
    llm_next_steps = llm_data.get("next_steps", [])
    if llm_next_steps or plan_items:
        step_items = []
        source_items = llm_next_steps if llm_next_steps else plan_items
        for i, item in enumerate(source_items):
            if isinstance(item, dict):
                text = item.get("text", "")
                key = item.get("schema_key", "")
            else:
                text = str(item)
                key = plan_items[i].get("schema_key", "") if i < len(plan_items) and isinstance(plan_items[i], dict) else ""
            badge = _command_badge(key) if key else _item_remove_btn()
            step_items.append(
                f'<li><span class="avs-item-text">{_esc(text)}</span>{badge}</li>'
            )
        steps_html = f'<ul>{"".join(step_items)}</ul>'
    else:
        steps_html = '<p>Continue with your regular care routine.</p>'
    sections.append(
        f'<div class="avs-section avs-removable" data-section="next-steps">'
        f'<div class="avs-section-header">'
        f'<h3>Next Steps</h3>{xbtn}</div>{steps_html}</div>'
    )

    # Warning signs (LLM generated)
    warnings = llm_data.get("warning_signs", [])
    rm = _item_remove_btn()
    if warnings:
        warn_list = _render_list(warnings, removable=True)
    else:
        warn_list = f'<ul><li><span class="avs-item-text">Any symptoms that worry you or get worse quickly</span>{rm}</li></ul>'
    sections.append(
        f'<div class="banner banner-warning avs-removable" data-section="when-to-seek-care">'
        f'<div class="avs-section-header">'
        f'<div class="banner-header" style="flex:1">When to Seek Care</div>{xbtn}</div>'
        f'<p>Go to the emergency room or call 911 if you experience:</p>'
        f'{warn_list}</div>'
    )

    # Questions
    sections.append(
        f'<div class="avs-section avs-removable" data-section="questions">'
        f'<div class="avs-section-header">'
        f'<h3>Questions?</h3>{xbtn}</div>'
        f'<p>Please contact our office if you have any questions about your care.</p></div>'
    )

    return "\n".join(sections)
