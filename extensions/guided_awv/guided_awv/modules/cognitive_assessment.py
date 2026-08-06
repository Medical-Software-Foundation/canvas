"""Cognitive Assessment module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


SCREENING_TOOLS = [
    {"id": "mini_cog", "label": "Mini-Cog", "max_score": 5, "cutoff": 2, "cutoff_dir": "le"},
    {"id": "moca", "label": "MoCA", "max_score": 30, "cutoff": 25, "cutoff_dir": "lt"},
    {"id": "slums", "label": "SLUMS", "max_score": 30, "cutoff": 20, "cutoff_dir": "lt"},
    {"id": "mmse", "label": "MMSE", "max_score": 30, "cutoff": 23, "cutoff_dir": "lt"},
]


class CognitiveAssessmentModule(BaseModule):
    """
    Cognitive Assessment section.

    Uses Mini-Cog screening: 3-item recall + clock drawing test.
    Structured to guide providers through the assessment steps
    and document the score.
    """

    ORDER = 10
    TITLE = "Cognitive Assessment"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-brain"

    MINI_COG_WORDS = ["Banana", "Sunrise", "Chair"]

    CLOCK_DRAWING_SCORES = [
        {"value": "2", "label": "2 - Normal (correct time on correctly drawn clock)"},
        {"value": "1", "label": "1 - Abnormal (incorrect time OR abnormal clock)"},
        {"value": "0", "label": "0 - No interpretable clock drawn"},
    ]

    def render_content_html(self) -> str:
        """Render cognitive assessment form with tool selector."""
        ctx = self.get_context()
        html = ""
        # Note: _alert escapes its text since v0.14.9, so <strong> tags and
        # &mdash;/&ge;/&le;/&rarr; entities here would render as literal text.
        # Use uppercase emphasis instead and native Unicode glyphs.
        html += self._alert(
            "COGNITIVE ASSESSMENT — Select the screening tool administered",
            "info",
        )

        # Tool selector radio group
        html += self._radio_group(
            "cognitive_tool",
            "Screening Tool",
            [{"value": t["id"], "label": t["label"]} for t in SCREENING_TOOLS],
        )
        html += self._divider()

        # --- Mini-Cog section (shown by default) ---
        html += '<div id="tool-mini_cog">'
        for inst in ctx["instructions"]:
            html += (
                f'<div style="margin-bottom:8px;padding:8px;background:#f8f9fa;'
                f'border-radius:4px;border-left:3px solid #1565c0;">'
                f'<strong>Step {inst["step"]}: {inst["title"]}</strong><br>'
                f'<span style="font-size:12px;">{inst["text"]}</span></div>'
            )
        html += self._divider()
        for field in ctx["fields"]:
            ftype = field.get("type", "text")
            freq = field.get("required", False)
            if ftype == "number":
                html += self._number_input(
                    field["id"], field["label"],
                    min_val=field.get("min", ""), max_val=field.get("max", ""),
                    readonly=field.get("readonly", False),
                    required=freq,
                )
            elif ftype == "select":
                html += self._select(field["id"], field["label"], field.get("options", []), required=freq)
            elif ftype == "textarea":
                html += self._textarea(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=freq)
            else:
                html += self._text_input(field["id"], field["label"], required=freq)
        # Interpretation display
        html += (
            '<div id="minicog-interpretation" class="awv-info-row" style="font-weight:600;margin-top:6px;">'
            '<span class="awv-info-label">Interpretation</span>'
            '<span class="awv-info-value" id="minicog-interpretation-value">--</span>'
            '</div>'
        )
        html += (
            '<div id="minicog-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            'Mini-Cog score ≤ 2: Positive screen for cognitive impairment. '
            'Consider further evaluation (e.g., MMSE, MoCA) and/or referral.</div>'
        )
        # _alert escapes - keep label emphasis via uppercase + Unicode arrow.
        html += self._alert(
            'CLOCK DRAWING UPLOAD: To upload a photo of the clock drawing, '
            'use the Visual Exam Finding command on your linked phone '
            '(Canvas iOS app → Document Visual Exam Finding).',
            'info',
        )
        html += '</div>'  # end tool-mini_cog

        # --- Alternative tool section (MoCA / SLUMS / MMSE) ---
        html += '<div id="tool-alt" style="display:none;">'
        html += (
            '<div id="alt-tool-info" class="awv-info-row" style="font-weight:600;margin-bottom:8px;">'
            '<span class="awv-info-label">Tool</span>'
            '<span class="awv-info-value" id="alt-tool-info-value">--</span>'
            '</div>'
        )
        html += self._number_input("alt_cog_score", "Total Score", min_val="0", max_val="30")
        html += self._textarea(
            "alt_cog_notes", "Clinical Observations",
            placeholder="Note any behavioral observations, language difficulties, or follow-up referrals.",
        )
        html += (
            '<div id="alt-cog-interpretation" class="awv-info-row" style="font-weight:600;margin-top:6px;">'
            '<span class="awv-info-label">Interpretation</span>'
            '<span class="awv-info-value" id="alt-cog-interpretation-value">--</span>'
            '</div>'
        )
        html += (
            '<div id="alt-cog-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            'Positive screen for cognitive impairment. Consider further evaluation and/or referral.</div>'
        )
        html += '</div>'  # end tool-alt

        # --- Shared sections (follow-up plan, screening completed, scoring) ---
        # Follow-up plan (shown when screen is positive)
        html += (
            '<div id="cognitive-followup-section" style="display:none;">'
        )
        html += self._divider()
        html += self._subtitle("Cognitive Follow-Up Plan")
        html += self._select(
            "cognitive_followup_plan",
            "Recommended follow-up action",
            [
                "No follow-up needed",
                "Referral to neuropsychology",
                "Full cognitive evaluation ordered",
                "Neurology referral",
                "Rescreen at next visit",
            ],
        )
        html += "</div>"

        html += self._divider()
        html += self._radio_group(
            "cognitive_screening_completed",
            "Cognitive screening completed?",
            ["Yes", "No - patient refused", "No - deferred"],
            required=True,
        )
        html += self._divider()
        html += self._subtitle("Scoring Interpretation")
        for score_range, interpretation in ctx["scoring"].items():
            html += self._info_row(score_range, interpretation)
        return f'<div class="awv-module-content">{html}{self._save_button("saveCognitiveAssessment", "Save Assessment")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return cognitive assessment context."""
        return {
            "assessment_name": "Mini-Cog",
            "instructions": [
                {
                    "step": 1,
                    "title": "Word Registration",
                    "text": (
                        f"Say to patient: 'I am going to say three words that I want you to remember. "
                        f"Please repeat them back to me now and try to remember them for a few minutes.' "
                        f"Words: {', '.join(self.MINI_COG_WORDS)}"
                    ),
                },
                {
                    "step": 2,
                    "title": "Clock Drawing",
                    "text": (
                        "Give patient paper and say: 'Please draw a clock face, put in all the numbers, "
                        "and set the hands to show 11:10.' "
                        "Scoring: 2 = Normal clock with correct time, 1 = Abnormal clock OR incorrect time, "
                        "0 = No interpretable clock."
                    ),
                },
                {
                    "step": 3,
                    "title": "Word Recall",
                    "text": "Ask patient: 'What were the three words I asked you to remember?'",
                },
            ],
            "recall_words": self.MINI_COG_WORDS,
            "clock_drawing_scores": self.CLOCK_DRAWING_SCORES,
            "scoring": {
                "0-2": "Positive screen - consider further evaluation",
                "3-5": "Negative screen (3 = borderline if clock abnormal)",
            },
            "fields": [
                {
                    "id": "words_recalled",
                    "label": "Number of words recalled (0-3)",
                    "type": "number",
                    "min": "0",
                    "max": "3",
                    "required": True,
                },
                {
                    "id": "clock_drawing_score",
                    "label": "Clock Drawing Score",
                    "type": "select",
                    "options": self.CLOCK_DRAWING_SCORES,
                    "required": True,
                },
                {
                    "id": "mini_cog_total",
                    "label": "Mini-Cog Total Score (0-5)",
                    "type": "number",
                    "readonly": True,
                    "note": "Auto-calculated: words recalled + clock score",
                },
                {
                    "id": "cognitive_notes",
                    "label": "Additional Clinical Observations",
                    "type": "textarea",
                    "placeholder": "Note any behavioral observations, language difficulties, or follow-up referrals.",
                },
            ],
            "note_id": self.note_id,
        }
