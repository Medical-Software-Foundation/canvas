"""Alcohol Screening (AUDIT-C) module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class AlcoholScreeningModule(BaseModule):
    """
    Alcohol Screening section using the AUDIT-C (Alcohol Use Disorders
    Identification Test - Consumption).

    A validated 3-question screening tool recommended by USPSTF for
    alcohol misuse. CMS covers alcohol misuse screening and brief
    counseling (G0442/G0443).
    """

    ORDER = 9
    TITLE = "Alcohol Screening (AUDIT-C)"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-wine-glass-alt"

    QUESTIONS = [
        {
            "id": "auditc_q1",
            "label": "How often do you have a drink containing alcohol?",
            "options": [
                {"value": "0", "label": "Never"},
                {"value": "1", "label": "Monthly or less"},
                {"value": "2", "label": "2-4 times a month"},
                {"value": "3", "label": "2-3 times a week"},
                {"value": "4", "label": "4 or more times a week"},
            ],
        },
        {
            "id": "auditc_q2",
            "label": "How many drinks containing alcohol do you have on a typical day when you are drinking?",
            "options": [
                {"value": "0", "label": "1 or 2"},
                {"value": "1", "label": "3 or 4"},
                {"value": "2", "label": "5 or 6"},
                {"value": "3", "label": "7, 8, or 9"},
                {"value": "4", "label": "10 or more"},
            ],
        },
        {
            "id": "auditc_q3",
            "label": "How often do you have 6 or more drinks on one occasion?",
            "options": [
                {"value": "0", "label": "Never"},
                {"value": "1", "label": "Less than monthly"},
                {"value": "2", "label": "Monthly"},
                {"value": "3", "label": "Weekly"},
                {"value": "4", "label": "Daily or almost daily"},
            ],
        },
    ]

    # AUDIT-C positive thresholds (USPSTF / VA guidelines)
    POSITIVE_THRESHOLD_MALE = 4
    POSITIVE_THRESHOLD_FEMALE = 3

    def render_content_html(self) -> str:
        """Render AUDIT-C screening form."""
        ctx = self.get_context()
        html = ""
        html += self._alert(ctx["billing_note"], "info")
        for q in ctx["questions"]:
            html += self._radio_group(q["id"], q["label"], q["options"], required=True)
        html += (
            '<div id="auditc-score" class="awv-info-row" style="font-weight:600;">'
            '<span class="awv-info-label">AUDIT-C Score</span>'
            '<span class="awv-info-value">--</span></div>'
        )
        html += (
            '<div id="auditc-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            'Positive AUDIT-C screen. CMS covers brief counseling (G0443). '
            'Document brief intervention and/or referral.</div>'
        )
        html += self._divider()
        scoring = ctx["scoring"]
        html += self._subtitle("Scoring")
        html += self._info_row("Max Score", str(scoring["max_score"]))
        html += self._info_row("Male Positive Threshold", f"≥ {scoring['male_threshold']}")
        html += self._info_row("Female Positive Threshold", f"≥ {scoring['female_threshold']}")
        for key, interp in scoring["interpretation"].items():
            html += self._info_row(key.title(), interp)
        return f'<div class="awv-module-content">{html}{self._save_button("saveAlcoholScreening", "Save Screening")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return AUDIT-C screening context."""
        return {
            "questions": self.QUESTIONS,
            "scoring": {
                "male_threshold": self.POSITIVE_THRESHOLD_MALE,
                "female_threshold": self.POSITIVE_THRESHOLD_FEMALE,
                "max_score": 12,
                "interpretation": {
                    "negative": "Low risk - no further intervention needed",
                    "positive": "Positive screen - brief intervention and/or referral recommended",
                },
            },
            "billing_note": (
                "Medicare covers annual alcohol misuse screening (G0442) and "
                "up to 4 brief face-to-face counseling sessions per year (G0443) "
                "for patients who screen positive."
            ),
            "note_id": self.note_id,
        }
