"""Hearing & Vision Screening module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class HearingVisionModule(BaseModule):
    """
    Hearing & Vision Screening section.

    CMS-required sensory assessment for the Annual Wellness Visit.
    Documents hearing and visual acuity screening results, use of
    assistive devices, and referral needs.
    """

    ORDER = 7
    TITLE = "Hearing & Vision Screening"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-eye"

    def render_content_html(self) -> str:
        """Render hearing and vision screening form."""
        ctx = self.get_context()
        html = ""
        html += self._subtitle("Hearing Assessment")
        for field in ctx["hearing_fields"]:
            ftype = field.get("type", "text")
            required = field.get("required", False)
            if ftype == "radio":
                html += self._radio_group(field["id"], field["label"], field["options"], required=required)
            else:
                html += self._text_input(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=required)
        html += self._divider()
        html += self._subtitle("Vision Assessment")
        for field in ctx["vision_fields"]:
            ftype = field.get("type", "text")
            required = field.get("required", False)
            if ftype == "radio":
                html += self._radio_group(field["id"], field["label"], field["options"], required=required)
            else:
                html += self._text_input(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=required)
        return f'<div class="awv-module-content">{html}{self._save_button("saveHearingVision", "Save Screening")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return hearing and vision screening context."""
        return {
            "hearing_fields": [
                {
                    "id": "hearing_subjective",
                    "label": "Does the patient report difficulty hearing?",
                    "type": "radio",
                    "options": ["No difficulty", "Mild difficulty", "Moderate difficulty", "Severe difficulty"],
                },
                {
                    "id": "hearing_aid_use",
                    "label": "Does the patient use hearing aids?",
                    "type": "radio",
                    "options": ["Yes - bilateral", "Yes - unilateral", "No", "Recommended but not using"],
                },
                {
                    "id": "whisper_test",
                    "label": "Whispered voice test (or audiometry if available)",
                    "type": "radio",
                    "options": ["Pass (both ears)", "Fail (right ear)", "Fail (left ear)", "Fail (both ears)", "Not performed"],
                },
                {
                    "id": "hearing_referral",
                    "label": "Audiology referral needed?",
                    "type": "radio",
                    "options": ["Yes", "No", "Already followed by audiology"],
                },
            ],
            "vision_fields": [
                {
                    "id": "vision_subjective",
                    "label": "Does the patient report difficulty seeing (even with glasses/contacts)?",
                    "type": "radio",
                    "options": ["No difficulty", "Mild difficulty", "Moderate difficulty", "Severe difficulty"],
                },
                {
                    "id": "corrective_lenses",
                    "label": "Does the patient use corrective lenses?",
                    "type": "radio",
                    "options": ["Yes - glasses", "Yes - contacts", "Yes - both", "No"],
                },
                {
                    "id": "snellen_right",
                    "label": "Visual acuity - right eye (Snellen)",
                    "type": "text",
                    "placeholder": "e.g., 20/20, 20/40",
                },
                {
                    "id": "snellen_left",
                    "label": "Visual acuity - left eye (Snellen)",
                    "type": "text",
                    "placeholder": "e.g., 20/20, 20/40",
                },
                {
                    "id": "last_eye_exam",
                    "label": "Date of last comprehensive eye exam",
                    "type": "text",
                    "placeholder": "e.g., 2025-06, Unknown",
                },
                {
                    "id": "vision_referral",
                    "label": "Ophthalmology/optometry referral needed?",
                    "type": "radio",
                    "options": ["Yes", "No", "Already followed by eye care"],
                },
            ],
            "note_id": self.note_id,
        }
