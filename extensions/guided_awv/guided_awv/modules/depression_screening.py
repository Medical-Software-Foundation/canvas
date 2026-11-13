"""Depression Screening (PHQ-2 / PHQ-9) module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class DepressionScreeningModule(BaseModule):
    """
    Depression Screening section.

    Initial screening with PHQ-2. If PHQ-2 score >= 3 (positive screen),
    expands automatically to full PHQ-9.
    """

    ORDER = 8
    TITLE = "Depression Screening (PHQ-2/PHQ-9)"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-brain"

    PHQ2_QUESTIONS = [
        {
            "id": "phq2_q1",
            "label": "Over the last 2 weeks, how often have you been bothered by little interest or pleasure in doing things?",
        },
        {
            "id": "phq2_q2",
            "label": "Over the last 2 weeks, how often have you been bothered by feeling down, depressed, or hopeless?",
        },
    ]

    PHQ9_ADDITIONAL_QUESTIONS = [
        {
            "id": "phq9_q3",
            "label": "Trouble falling asleep, staying asleep, or sleeping too much?",
        },
        {
            "id": "phq9_q4",
            "label": "Feeling tired or having little energy?",
        },
        {
            "id": "phq9_q5",
            "label": "Poor appetite or overeating?",
        },
        {
            "id": "phq9_q6",
            "label": "Feeling bad about yourself — or that you are a failure or have let yourself or your family down?",
        },
        {
            "id": "phq9_q7",
            "label": "Trouble concentrating on things, such as reading the newspaper or watching television?",
        },
        {
            "id": "phq9_q8",
            "label": "Moving or speaking so slowly that other people could have noticed? Or the opposite — being so fidgety or restless that you have been moving around a lot more than usual?",
        },
        {
            "id": "phq9_q9",
            "label": "Thoughts that you would be better off dead or of hurting yourself in some way?",
        },
    ]

    RESPONSE_OPTIONS = [
        {"value": "0", "label": "Not at all"},
        {"value": "1", "label": "Several days"},
        {"value": "2", "label": "More than half the days"},
        {"value": "3", "label": "Nearly every day"},
    ]

    def render_content_html(self) -> str:
        """Render PHQ-2/PHQ-9 screening form."""
        ctx = self.get_context()
        html = ""
        html += self._alert(
            "PHQ-2 Screening: Score ≥ 3 is a positive screen. "
            "Proceed to full PHQ-9 if positive.", "info",
        )
        html += self._subtitle("PHQ-2 (Initial Screen)")
        for q in ctx["phq2_questions"]:
            html += self._radio_group(q["id"], q["label"], ctx["response_options"], required=True)
        html += (
            '<div id="phq2-score" class="awv-info-row" style="font-weight:600;">'
            '<span class="awv-info-label">PHQ-2 Score</span>'
            '<span class="awv-info-value">--</span></div>'
        )
        html += (
            '<div id="phq2-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            'PHQ-2 score ≥ 3: Positive screen. Complete full PHQ-9 below.</div>'
        )
        html += self._divider()
        # PHQ-9 section: hidden until PHQ-2 >= 3, toggled by scorePHQ() JS
        html += '<div id="phq9-section" style="display:none;">'
        html += self._subtitle("PHQ-9 (Full Assessment)")
        html += '<p style="font-size:11px;color:#666;margin-bottom:8px;">Complete if PHQ-2 score ≥ 3</p>'
        for q in ctx["phq9_additional_questions"]:
            html += self._radio_group(q["id"], q["label"], ctx["response_options"], required=True)
        html += (
            '<div id="phq9-score" class="awv-info-row" style="font-weight:600;">'
            '<span class="awv-info-label">PHQ-9 Total Score</span>'
            '<span class="awv-info-value">--</span></div>'
        )
        html += (
            '<div id="phq9-severity" class="awv-info-row">'
            '<span class="awv-info-label">Severity</span>'
            '<span class="awv-info-value">--</span></div>'
        )
        html += '</div>'
        # Depression follow-up section (shown when PHQ-2 >= 3)
        html += (
            '<div id="depression-followup-section" style="display:none;">'
        )
        html += self._divider()
        html += self._subtitle("Safety Assessment & Treatment Plan")
        html += self._radio_group(
            "safety_assessed",
            "Safety assessment",
            [
                {"value": "assessed_no_risk", "label": "Assessed - no safety risk identified"},
                {"value": "assessed_safety_plan", "label": "Assessed - safety plan in place"},
                {"value": "assessed_crisis_referral", "label": "Assessed - crisis referral made"},
                {"value": "not_assessed", "label": "Not assessed"},
            ],
        )
        html += self._radio_group(
            "suicide_ideation_assessed",
            "Was suicide ideation assessed?",
            ["Yes", "No", "N/A - PHQ-2 negative"],
            required=True,
        )
        html += self._radio_group(
            "suicide_ideation_present",
            "Is suicide ideation present?",
            ["Yes", "No", "N/A"],
        )
        html += self._select(
            "depression_treatment_plan",
            "Treatment plan",
            [
                "No treatment indicated",
                "Brief counseling provided",
                "Medication initiated/adjusted",
                "Behavioral health referral",
                "Psychiatry referral",
                "Follow-up appointment scheduled",
                "Combination (medication + therapy referral)",
            ],
        )
        html += self._textarea(
            "depression_treatment_notes",
            "Treatment plan details",
            placeholder="Document treatment decisions, medications prescribed, referrals made, and follow-up plan.",
        )
        html += "</div>"

        html += self._divider()
        html += self._subtitle("Scoring Reference")
        for severity, range_str in ctx["phq9_severity"].items():
            html += self._info_row(severity.replace("_", " ").title(), range_str)
        return f'<div class="awv-module-content">{html}{self._save_button("saveDepressionScreening", "Save Screening")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return depression screening context."""
        return {
            "phq2_questions": self.PHQ2_QUESTIONS,
            "phq9_additional_questions": self.PHQ9_ADDITIONAL_QUESTIONS,
            "response_options": self.RESPONSE_OPTIONS,
            "phq2_positive_threshold": 3,
            "phq9_severity": {
                "minimal": "0-4",
                "mild": "5-9",
                "moderate": "10-14",
                "moderately_severe": "15-19",
                "severe": "20-27",
            },
            "note_id": self.note_id,
        }
