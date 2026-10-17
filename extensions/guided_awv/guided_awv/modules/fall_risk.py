"""Fall Risk Assessment module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class FallRiskModule(BaseModule):
    """
    Fall Risk Assessment section.

    Screens for fall history, gait/balance, and medications that increase
    fall risk. Uses validated Timed Up and Go (TUG) test prompts when
    appropriate.
    """

    ORDER = 13
    TITLE = "Fall Risk Assessment"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-person-falling"

    def render_content_html(self) -> str:
        """Render fall risk assessment form."""
        ctx = self.get_context()
        html = ""
        html += self._subtitle("Screening Questions")
        for q in ctx["screening_questions"]:
            conditional_on = q.get("conditional_on")
            conditional_value = q.get("conditional_value")
            if conditional_on:
                html += (
                    f'<div class="awv-conditional" '
                    f'data-conditional-on="{conditional_on}" '
                    f'data-conditional-value="{conditional_value}" '
                    f'style="display:none;">'
                )
            ftype = q.get("type", "text")
            freq = q.get("required", False)
            if ftype == "radio":
                html += self._radio_group(q["id"], q["label"], q["options"], required=freq)
            elif ftype == "number":
                html += self._number_input(q["id"], q["label"], required=freq)
            if conditional_on:
                html += '</div>'
        html += (
            '<div id="steadi-result" class="awv-info-row" style="margin-top:6px;">'
            '<span class="awv-info-label">STEADI Screen Result</span>'
            '<span class="awv-info-value" id="steadi-result-value">--</span>'
            '</div>'
        )
        html += '<div id="steadi-assessment" style="display:none;">'
        html += self._divider()
        tug = ctx["tug_test"]
        html += self._subtitle(tug["name"])
        html += self._alert(tug["instructions"], "info")
        field = tug["field"]
        html += self._number_input(field["id"], field["label"], step=field.get("step", ""), required=True)
        html += self._divider()
        ortho = ctx["orthostatic_vitals"]
        html += self._subtitle(ortho["name"])
        html += self._alert(ortho["instructions"], "info")
        html += '<h4 style="font-size:12px;font-weight:600;margin:8px 0 4px;">Lying (Supine)</h4>'
        for f in ortho["lying_fields"]:
            html += self._number_input(f["id"], f["label"], step="1")
        html += '<h4 style="font-size:12px;font-weight:600;margin:8px 0 4px;">Standing</h4>'
        for f in ortho["standing_fields"]:
            html += self._number_input(f["id"], f["label"], step="1")
        for f in ortho["result_fields"]:
            html += self._number_input(f["id"], f["label"], step="1", readonly=f.get("readonly", False))
        html += (
            '<div id="ortho-result" class="awv-info-row" style="margin-top:6px;">'
            '<span class="awv-info-label">Orthostatic Result</span>'
            '<span class="awv-info-value" id="ortho-result-value">--</span>'
            '</div>'
        )
        html += (
            '<div id="ortho-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            'Positive orthostatic hypotension detected. '
            'SBP drop \u2265 20 mmHg or DBP drop \u2265 10 mmHg on standing. '
            'Consider medication review and fall prevention interventions.'
            '</div>'
        )
        html += '</div>'
        html += self._divider()
        html += self._subtitle("Risk Factors to Assess")
        html += self._checkbox_group("fall_risk_factors", "Identified risk factors", ctx["risk_factors"])
        html += self._divider()
        html += self._subtitle("Overall Fall Risk Level")
        html += (
            '<div id="fall-risk-level" class="awv-info-row">'
            '<span class="awv-info-label">Risk Level</span>'
            '<span class="awv-info-value">--</span>'
            '</div>'
        )
        html += (
            '<div id="fall-risk-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            'High fall risk identified. Recommend multifactorial fall risk intervention: '
            'medication review, vitamin D supplementation, physical therapy referral, '
            'and home safety evaluation per CDC STEADI guidelines.'
            '</div>'
        )

        # Fall intervention plan (shown when risk level = High)
        html += (
            '<div id="fall-intervention-section" style="display:none;">'
        )
        html += self._divider()
        html += self._subtitle("Fall Intervention Plan")
        html += self._textarea(
            "fall_intervention_plan",
            "Intervention plan for high-risk patient",
            placeholder="Document planned interventions: medication review, PT referral, "
            "vitamin D, home safety evaluation, vision correction, footwear assessment, etc.",
        )
        html += "</div>"

        return f'<div class="awv-module-content">{html}{self._save_button("saveFallRisk", "Save Fall Risk")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return fall risk context."""
        return {
            "screening_questions": [
                {
                    "id": "falls_past_year",
                    "label": "Have you fallen in the past year?",
                    "type": "radio",
                    "options": ["Yes", "No"],
                    "required": True,
                },
                {
                    "id": "falls_count",
                    "label": "If yes, how many times?",
                    "type": "number",
                    "conditional_on": "falls_past_year",
                    "conditional_value": "Yes",
                },
                {
                    "id": "fall_injury",
                    "label": "Did any fall result in injury?",
                    "type": "radio",
                    "options": ["Yes", "No"],
                    "conditional_on": "falls_past_year",
                    "conditional_value": "Yes",
                },
                {
                    "id": "fear_of_falling",
                    "label": "Are you afraid of falling?",
                    "type": "radio",
                    "options": ["Yes", "No"],
                    "required": True,
                },
                {
                    "id": "gait_concern",
                    "label": "Do you feel unsteady when standing or walking?",
                    "type": "radio",
                    "options": ["Yes", "No"],
                    "required": True,
                },
                {
                    "id": "assistive_device",
                    "label": "Do you use a cane, walker, or other assistive device for walking?",
                    "type": "radio",
                    "options": ["Yes - cane", "Yes - walker", "Yes - other", "No"],
                },
            ],
            "tug_test": {
                "name": "Timed Up and Go (TUG) Test",
                "instructions": (
                    "Ask patient to: Stand up from chair, walk 10 feet, turn around, "
                    "walk back, and sit down. Time in seconds. "
                    "Interpretation: < 12 seconds = low fall risk, >= 12 seconds = increased risk."
                ),
                "field": {
                    "id": "tug_time_seconds",
                    "label": "TUG Test Time (seconds)",
                    "type": "number",
                    "step": "0.1",
                },
            },
            "orthostatic_vitals": {
                "name": "Orthostatic (Postural) Vital Signs",
                "instructions": (
                    "1. Patient lies supine 3-5 min, record BP and HR. "
                    "2. Patient stands, wait 1-3 min, record BP and HR. "
                    "Positive: SBP drop >= 20 mmHg OR DBP drop >= 10 mmHg."
                ),
                "lying_fields": [
                    {"id": "ortho_lying_sbp", "label": "Lying Systolic BP (mmHg)"},
                    {"id": "ortho_lying_dbp", "label": "Lying Diastolic BP (mmHg)"},
                    {"id": "ortho_lying_hr", "label": "Lying Heart Rate (bpm)"},
                ],
                "standing_fields": [
                    {"id": "ortho_standing_sbp", "label": "Standing Systolic BP (mmHg)"},
                    {"id": "ortho_standing_dbp", "label": "Standing Diastolic BP (mmHg)"},
                    {"id": "ortho_standing_hr", "label": "Standing Heart Rate (bpm)"},
                ],
                "result_fields": [
                    {"id": "ortho_sbp_drop", "label": "SBP Drop (mmHg)", "readonly": True},
                    {"id": "ortho_dbp_drop", "label": "DBP Drop (mmHg)", "readonly": True},
                ],
            },
            "risk_factors": [
                "History of falls",
                "Gait/balance problems",
                "Polypharmacy (>4 medications)",
                "Orthostatic hypotension",
                "Psychotropic medications",
                "Vitamin D deficiency",
                "Visual impairment",
                "Foot problems",
                "Environmental hazards",
            ],
            "note_id": self.note_id,
        }
