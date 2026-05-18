"""Phase E: render the printable Nutrition Note HTML.

Visual style follows the **home-app print convention** as captured in the
`scribe_print_button` reference plugin (`templates/print_base.html`):

  - System sans-serif (`-apple-system, BlinkMacSystemFont, ...`), 15px body
  - Greys for body text + borders, navy `#052B49` for section headers
  - Patient block on the left (big name, DOB badge, "Seen by ...") and
    practice info on the right of the header row
  - Each subsection is a bordered `.content-block` card with a small
    uppercase `.command-label` and the body underneath
  - `@page` margins + running footer with patient identifiers and
    page-of-pages count, auto-print on load

We keep the same `render_print_html(payload)` surface so the API and tests
don't change. Body content is adapted to ADIME (not SOAP) but the chrome
mirrors home-app verbatim where it makes sense.

Practice info is sourced from the `practice-name`, `practice-address`,
`practice-phone`, and `practice-fax` plugin secrets so each Canvas instance
can carry its own branding without a code change.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

LOGO_URL = ""  # set when a logo asset is finalized


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value))


def _bullet_lines(items: list[str]) -> str:
    """Plain text lines for content-block bodies. One <div> per item so the
    home-app layout doesn't introduce stray <ul> indentation."""
    if not items:
        return ""
    return "".join(
        f'<div class="content-line">{_esc(item)}</div>'
        for item in items if item
    )


def _qa_lines(rows: list[dict[str, str]]) -> str:
    """Question/answer pairs rendered like home-app's questionnaire block:
    `<strong>Label:</strong> answer`, one per line."""
    if not rows:
        return ""
    return "".join(
        f'<div class="content-line"><strong>{_esc(row.get("label", ""))}:</strong> '
        f'{_esc(row.get("text", ""))}</div>'
        for row in rows
    )


def _vitals_items(pairs: list[tuple[str, Any, str]]) -> str:
    """Home-app vitals pattern: flex-wrap items with a bold label, value, unit."""
    items = [
        f'<span class="vitals-item"><strong>{_esc(label)}</strong> '
        f"{_esc(value)}{(' ' + _esc(unit)) if unit else ''}</span>"
        for label, value, unit in pairs
        if value not in (None, "", 0)
    ]
    return f'<div class="vitals-values">{"".join(items)}</div>' if items else ""


def _anthro_block(anthro: dict[str, Any]) -> str:
    pairs = [
        ("Height", anthro.get("height"), "in"),
        ("Weight", anthro.get("weight"), "lb"),
        ("BMI", anthro.get("bmi"), ""),
        ("UBW", anthro.get("ubw"), "lb"),
        ("IBW", anthro.get("ibw"), "lb"),
    ]
    return _vitals_items(pairs)


def _requirements_block(requirements: dict[str, Any]) -> str:
    pairs = [
        ("Calories", requirements.get("calories"), "kcal/day"),
        ("Protein", requirements.get("protein"), "g/day"),
        ("Carbohydrates", requirements.get("carbohydrates"), "g/day"),
        ("Fluid", requirements.get("fluid"), "mL/day"),
    ]
    return _vitals_items(pairs)


def _pmh_items(pmh: list[Any]) -> list[str]:
    out = []
    for entry in pmh or []:
        if not isinstance(entry, dict):
            continue
        display = (entry.get("display") or "").strip()
        code = (entry.get("code") or "").strip()
        if not display:
            continue
        out.append(f"{display} ({code})" if code else display)
    return out


def _allergy_items(allergies: list[Any]) -> list[str]:
    out = []
    for entry in allergies or []:
        if not isinstance(entry, dict):
            continue
        label = entry.get("display") or entry.get("narrative") or ""
        severity = entry.get("severity") or ""
        if not label:
            continue
        out.append(f"{label} ({severity})" if severity else label)
    return out


def _med_items(meds: list[Any]) -> list[str]:
    return [
        m.get("display", "") for m in (meds or [])
        if isinstance(m, dict) and m.get("display")
    ]


def _lab_lines(labs: list[Any]) -> str:
    """Recent labs as content-lines: `Lab name: value units (date)`."""
    items = []
    for lab in labs or []:
        if not isinstance(lab, dict):
            continue
        label = lab.get("label", "")
        if not label:
            continue
        value = str(lab.get("value", "")).strip()
        units = (lab.get("units") or "").strip()
        date = (lab.get("effective_date") or "").strip()
        rhs = ""
        if value:
            rhs = f"{value} {units}".strip()
        if date:
            rhs = f"{rhs} ({date})" if rhs else f"({date})"
        items.append(
            f'<div class="content-line"><strong>{_esc(label)}:</strong> '
            f"{_esc(rhs)}</div>"
        )
    return "".join(items)


def _content_block(label: str, body: str) -> str:
    """One bordered card matching home-app's `.content-block`. Suppressed
    entirely when the body is empty so follow-up prints stay tight."""
    if not body:
        return ""
    return (
        '<div class="content-block">'
        f'<div class="command-label">{_esc(label)}</div>'
        f"{body}"
        "</div>"
    )


def _section_header(text: str) -> str:
    return f'<div class="soap-header">{_esc(text)}</div>'


def _visit_type_label(value: str) -> str:
    return "Follow-up" if value == "follow_up" else "Initial"


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def _parse_dt(raw: Any) -> datetime | None:
    """Robust ISO-ish parser. `datetime.fromisoformat` handles microseconds
    and timezone offsets in 3.11+, including the "2026-05-04 17:30:47.864722+00:00"
    shape Django emits. Falls back to a few legacy formats if that fails."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_date(raw: Any) -> str:
    """Render as `m/d/yy` (e.g. 5/4/26). Empty/unparseable input returns ""."""
    dt = _parse_dt(raw)
    if dt is None:
        return ""
    return dt.strftime("%-m/%-d/%y")


def _format_datetime(raw: Any) -> str:
    """Render as `m/d/yyyy h:MM AM/PM` for the visit date-of-service. Drops
    the microseconds + timezone noise the dietician reported as excessive."""
    dt = _parse_dt(raw)
    if dt is None:
        return ""
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return dt.strftime("%-m/%-d/%Y")
    return dt.strftime("%-m/%-d/%Y %-I:%M %p")


def render_print_html(payload: dict[str, Any]) -> str:
    """Render the full printable Nutrition Note HTML document."""

    patient = payload.get("patient") or {}
    note = payload.get("note") or {}
    chart = payload.get("chart") or {}
    anthro = payload.get("anthropometrics") or {}
    questionnaires = payload.get("questionnaires") or {}
    requirements = payload.get("estimated_requirements") or {}
    intervention = payload.get("intervention") or {}
    monitoring = payload.get("monitoring") or {}
    coordination = payload.get("coordination") or {}
    monitor_team = coordination.get("monitor_team_meeting") or {}

    visit_label = _visit_type_label(payload.get("visit_type") or "initial")

    patient_name = _esc(patient.get("full_name")) or "—"
    patient_dob_raw = patient.get("birth_date") or ""
    patient_dob = _esc(_format_date(patient_dob_raw))
    patient_mrn = _esc(patient.get("mrn") or "")
    note_type = _esc(note.get("note_type_name") or f"Nutrition {visit_label}")
    date_of_service = _esc(_format_datetime(note.get("datetime_of_service") or ""))
    provider_name = _esc(note.get("provider_name")) or "—"

    # Practice info comes from per-customer secrets injected by the API.
    # Empty strings fall through to clean placeholder lines rather than
    # printing "None".
    practice = payload.get("practice") or {}
    practice_name = _esc(practice.get("name") or "")
    practice_address = _esc(practice.get("address") or "")
    practice_phone = _esc(practice.get("phone") or "")
    practice_fax = _esc(practice.get("fax") or "")
    now_str = datetime.now().strftime("%-m/%-d/%y %-I:%M %p")
    now_long = datetime.now().strftime("%b %-d, %Y %-I:%M %p")

    # ---- Build each ADIME section as a list of content-blocks -------------
    assessment_inner = "".join([
        _content_block("Past Medical History", _bullet_lines(_pmh_items(chart.get("pmh") or []))),
        _content_block("Allergies", _bullet_lines(_allergy_items(chart.get("allergies") or []))),
        _content_block(
            "Significant Nutrition Medications",
            _bullet_lines(_med_items(chart.get("medications") or [])),
        ),
        _content_block("Anthropometrics", _anthro_block(anthro)),
        _content_block("Recent Labs (last 90 days)", _lab_lines(chart.get("labs") or [])),
        _content_block(
            "Social and Diet History",
            _qa_lines(questionnaires.get("social_diet_history") or []),
        ),
        _content_block(
            "Dietary Intake",
            _qa_lines(questionnaires.get("dietary_intake") or []),
        ),
        _content_block(
            "Nutrition Focused Physical Exam",
            _qa_lines(questionnaires.get("nfpe") or []),
        ),
        _content_block(
            "Estimated Nutrition Requirements",
            _requirements_block(requirements),
        ),
    ])

    diagnosis_inner = _content_block(
        "Nutrition Diagnosis (PES)",
        _qa_lines(questionnaires.get("nutrition_diagnosis_pes") or []),
    )

    intervention_inner = "".join([
        _content_block(
            "Educational Materials Provided",
            _bullet_lines(intervention.get("educational_materials") or []),
        ),
        _content_block(
            "Counseling Narrative",
            f'<div class="command-text">{_esc(intervention.get("counseling_narrative") or "")}</div>'
            if intervention.get("counseling_narrative") else "",
        ),
    ])

    follow_up_date = _esc(_format_date(monitoring.get("follow_up_date") or ""))
    follow_up_comment = _esc(monitoring.get("follow_up_comment"))
    follow_up_body = ""
    if follow_up_date:
        follow_up_body = (
            f'<div class="content-line"><strong>Date:</strong> {follow_up_date}</div>'
        )
        if follow_up_comment:
            follow_up_body += (
                f'<div class="content-line"><strong>Reason:</strong> '
                f"{follow_up_comment}</div>"
            )

    monitoring_inner = "".join([
        _content_block(
            "Goals (as verbalized by patient)",
            _bullet_lines(monitoring.get("goals") or []),
        ),
        _content_block("Follow-up Appointment", follow_up_body),
    ])

    # Suppress this block entirely when the dietician didn't check the box
    # and didn't leave a comment — surfacing "No" on every print would be
    # noisy.
    monitor_checked = bool(monitor_team.get("checked"))
    monitor_comment = _esc(monitor_team.get("comment"))
    if monitor_checked or monitor_comment:
        monitor_yn = _yes_no(monitor_checked)
        monitor_body = (
            f'<div class="content-line"><strong>Monitor at next team meeting:</strong> '
            f"{monitor_yn}</div>"
        )
        if monitor_comment:
            monitor_body += (
                f'<div class="content-line">{monitor_comment}</div>'
            )
    else:
        monitor_body = ""

    coordination_inner = "".join([
        _content_block(
            "Collaboration / Referrals",
            _bullet_lines(coordination.get("referrals") or []),
        ),
        _content_block(
            "Recommended Labs",
            _bullet_lines(coordination.get("recommended_labs") or []),
        ),
        _content_block(
            "Recommended Supplementation",
            f'<div class="command-text">{_esc(coordination.get("recommended_supplementation") or "")}</div>'
            if coordination.get("recommended_supplementation") else "",
        ),
        _content_block("Monitor at Team Meeting", monitor_body),
    ])

    body_html_parts = []
    if assessment_inner:
        body_html_parts.append(_section_header("Nutrition Assessment"))
        body_html_parts.append(assessment_inner)
    if diagnosis_inner:
        body_html_parts.append(_section_header("Nutrition Diagnosis"))
        body_html_parts.append(diagnosis_inner)
    if intervention_inner:
        body_html_parts.append(_section_header("Nutrition Intervention"))
        body_html_parts.append(intervention_inner)
    if monitoring_inner:
        body_html_parts.append(_section_header("Nutrition Monitoring & Evaluation"))
        body_html_parts.append(monitoring_inner)
    if coordination_inner:
        body_html_parts.append(_section_header("Coordination of Care"))
        body_html_parts.append(coordination_inner)
    body_html = "".join(body_html_parts)

    logo_html = (
        f'<img class="practice-logo" src="{_esc(LOGO_URL)}" alt="">' if LOGO_URL else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{note_type} — {patient_name}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.4; color: #333; background: #fff;
  padding: 0.5in;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}}

/* --- Header --- */
.header {{ border-bottom: 1px solid #d1d5db; padding-bottom: 16px; margin-bottom: 14px; }}
.header-row {{ display: flex; justify-content: space-between; align-items: stretch; }}
.header-left {{ flex: 1; display: flex; flex-direction: column; justify-content: space-between; }}
.header-top {{
  font-size: 11px; font-weight: 400; text-transform: uppercase;
  letter-spacing: 0.1em; color: #6b7280; line-height: 1;
}}
.header-top .header-date {{ font-weight: 400; letter-spacing: 0.1em; color: #6b7280; }}
.patient-name {{
  font-size: 30px; font-weight: 700; color: #000;
  margin: 6px 0; letter-spacing: -0.02em; line-height: 1;
}}
.patient-summary {{
  display: flex; align-items: center; gap: 12px;
  font-size: 13px; color: #333; line-height: 1;
}}
.dob-badge {{
  display: inline-block; font-weight: 700; font-size: 11px;
  border: 1.5px solid #000; border-radius: 3px; padding: 2px 6px;
}}
.patient-summary strong {{ font-weight: 600; }}
.practice-info {{
  text-align: right; font-size: 11px; color: #6b7280; line-height: 1.5;
  flex-shrink: 0; display: flex; flex-direction: column; justify-content: space-between;
}}
.practice-logo {{
  display: block; height: auto; width: auto;
  max-height: 30px; max-width: 140px; object-fit: contain;
  margin-left: auto; margin-bottom: 2px;
}}
.practice-details {{ margin-top: auto; }}
.practice-name {{ font-weight: 400; color: #6b7280; font-size: 11px; }}
.practice-contact {{ color: #333; }}
.practice-contact strong {{ font-weight: 600; }}

/* --- Section headers --- */
.soap-header {{
  font-size: 16px; font-weight: 700; color: #052B49;
  text-transform: uppercase; letter-spacing: 0.3px;
  margin-top: 14px; margin-bottom: 8px;
}}
.soap-header:first-child {{ margin-top: 0; }}

/* --- Content block (each subsection) --- */
.content-block {{
  background: #fff; border: 1.5px solid #e8e8ec; border-radius: 8px;
  padding: 10px 14px; margin-bottom: 8px;
}}
.command-label {{
  font-size: 11px; font-weight: 700; color: #6b7280;
  text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;
}}
.content-line {{ font-size: 15px; line-height: 1.5; color: #333; }}
.content-line + .content-line {{ margin-top: 2px; }}
.command-text {{ font-size: 15px; line-height: 1.5; color: #333; white-space: pre-line; }}

.vitals-values {{
  display: flex; flex-wrap: wrap; gap: 6px 18px;
  font-size: 15px; line-height: 1.5; color: #333;
}}
.vitals-item {{ padding: 2px 0; }}
.vitals-item strong {{ font-weight: 600; color: #555; margin-right: 2px; }}

/* --- On-screen footer (hidden in print) --- */
.screen-footer {{
  margin-top: 12px; padding: 8px 0;
  font-size: 12px; color: #6b7280; border-top: 1px solid #d1d5db;
}}
.screen-footer-line {{ display: flex; justify-content: space-between; }}
.confidential {{ text-align: center; font-size: 11px; margin-top: 4px; }}

/* --- Print + Close toolbar (hidden in print) --- */
.toolbar {{
  position: sticky; top: 0; z-index: 10;
  display: flex; gap: 8px; justify-content: flex-end;
  padding: 8px 0 12px 0; margin-bottom: 8px;
  background: #fff;
}}
.toolbar button {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 13px; font-weight: 600;
  padding: 6px 14px; border-radius: 4px; cursor: pointer;
  border: 1px solid #052B49; background: #fff; color: #052B49;
}}
.toolbar button.primary {{ background: #052B49; color: #fff; }}
.toolbar button:hover {{ filter: brightness(0.95); }}

/* --- Print --- */
@media print {{
  body {{ padding: 0.25in 0 0 0; orphans: 3; widows: 3; }}
  @page {{
    margin: 0.25in 0.5in 0.8in 0.5in;
    @bottom-left {{
      content: "{patient_name} \\2022  DOB {patient_dob} \\2022  MRN {patient_mrn} \\2022  Printed {now_str}\\A Contains Confidential Information \\2013  Dispose of Properly";
      white-space: pre-wrap; font-size: 9px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #555; border-top: 1px solid #d1d5db; padding-top: 8px; vertical-align: top;
    }}
    @bottom-right {{
      content: "Page " counter(page) " of " counter(pages);
      font-size: 9px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #555; border-top: 1px solid #d1d5db; padding-top: 8px; vertical-align: top;
    }}
    @top-left {{ content: ""; }}
    @top-center {{ content: ""; }}
    @top-right {{ content: ""; }}
  }}
  .screen-footer {{ display: none; }}
  .toolbar {{ display: none; }}
  .soap-header {{ page-break-after: avoid; }}
  .content-block {{ break-inside: auto; }}
  .command-label {{ page-break-after: avoid; }}
  .vitals-values {{ page-break-inside: avoid; }}
}}
</style>
</head>
<body>
<div class="toolbar">
  <button type="button" id="nc-print-btn" class="primary">Print</button>
  <button type="button" id="nc-close-btn">Close</button>
</div>
<div class="header">
  <div class="header-row">
    <div class="header-left">
      <div class="header-top">
        {note_type.upper()} &nbsp;<span class="header-date">|&nbsp; Date of Service: {date_of_service}</span>
      </div>
      <div class="patient-name">{patient_name}</div>
      <div class="patient-summary">
        <span class="dob-badge">DOB {patient_dob}</span>
        <span>Seen by <strong>{provider_name}</strong>{f" at {practice_name}" if practice_name else ""}</span>
      </div>
    </div>
    <div class="practice-info">
      {logo_html}
      <div class="practice-details">
        {f'<div class="practice-name">{practice_name}</div>' if practice_name else ''}
        {f'<div>{practice_address}</div>' if practice_address else ''}
        {('<div class="practice-contact">'
          + (f'<strong>P:</strong> {practice_phone}' if practice_phone else '')
          + (' &nbsp; ' if practice_phone and practice_fax else '')
          + (f'<strong>F:</strong> {practice_fax}' if practice_fax else '')
          + '</div>') if (practice_phone or practice_fax) else ''}
      </div>
    </div>
  </div>
</div>

{body_html}

<div class="screen-footer">
  <div class="screen-footer-line">
    <span>{patient_name} | DOB: {patient_dob} | MRN: {patient_mrn}</span>
    <span>Printed: {_esc(now_long)}</span>
  </div>
  <div class="confidential">Contains Confidential Information — Dispose of Properly</div>
</div>

<script>
(function() {{
  // Capture the Canvas modal message port so the Close button can dismiss
  // the modal cleanly. Same INIT_CHANNEL handshake other plugins use
  // (e.g. patient-portal-forms / vida-guided-consult).
  var messagePort = null;
  window.addEventListener("message", function(event) {{
    if (event.data && event.data.type === "INIT_CHANNEL" && event.ports && event.ports[0]) {{
      messagePort = event.ports[0];
      messagePort.start();
    }}
  }});

  function triggerPrint() {{ window.print(); }}
  function closeModal() {{
    if (messagePort) {{
      messagePort.postMessage({{ type: "CLOSE_MODAL" }});
    }} else {{
      // Fallback: best-effort if the host hasn't finished the INIT_CHANNEL
      // handshake yet (rare). Doesn't actually close inside an iframe but
      // gives the user *some* signal.
      try {{ window.close(); }} catch (e) {{}}
    }}
  }}

  window.addEventListener("load", function() {{
    var printBtn = document.getElementById("nc-print-btn");
    var closeBtn = document.getElementById("nc-close-btn");
    if (printBtn) printBtn.addEventListener("click", triggerPrint);
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    // Auto-open the print dialog so the dietician doesn't have to click
    // the toolbar Print button on every open. They can cancel + review +
    // re-print using the toolbar.
    triggerPrint();
  }});
}})();
</script>
</body>
</html>"""
