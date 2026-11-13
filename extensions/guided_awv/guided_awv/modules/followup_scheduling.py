"""Follow-Up / Scheduling module."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class FollowUpSchedulingModule(BaseModule):
    """
    Follow-Up / Scheduling section.

    Schedules next AWV, follow-up appointments, and creates any tasks
    identified during the visit.
    """

    ORDER = 17
    TITLE = "Follow-Up / Scheduling"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-calendar-check"

    def render_content_html(self) -> str:
        """Render follow-up scheduling form."""
        ctx = self.get_context()
        html = ""
        for field in ctx["followup_fields"]:
            ftype = field.get("type", "text")
            freq = field.get("required", False)
            if ftype == "select":
                html += self._select(field["id"], field["label"], field.get("options", []), required=freq)
            elif ftype == "radio":
                html += self._radio_group(field["id"], field["label"], field["options"], required=freq)
            elif ftype == "textarea":
                html += self._textarea(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=freq)
            elif ftype == "date":
                req_star = ' <span class="awv-required">*</span>' if freq else ""
                req_attr = ' data-required="true"' if freq else ""
                default_val = field.get("default", "")
                val_attr = f' value="{default_val}"' if default_val else ""
                html += (
                    f'<div class="awv-field">'
                    f'<label class="awv-label">{field["label"]}{req_star}</label>'
                    f'<input type="date" name="{field["id"]}" class="awv-input"{req_attr}{val_attr}>'
                    f'</div>'
                )
            else:
                html += self._text_input(field["id"], field["label"], required=freq)
        html += self._divider()
        html += self._subtitle("Visit Tasks")
        html += self._checkbox_group("followup_tasks", "Tasks to complete", ctx["task_options"])
        return f'<div class="awv-module-content">{html}{self._save_button("saveFollowUp", "Save Follow-Up")}</div>'

    @staticmethod
    def _next_awv_default_date() -> str:
        """Return today + 1 year as YYYY-MM-DD string."""
        today = date.today()
        try:
            return today.replace(year=today.year + 1).isoformat()
        except ValueError:
            # Feb 29 -> Feb 28 in non-leap year
            return today.replace(year=today.year + 1, day=28).isoformat()

    def get_context(self) -> dict[str, Any]:
        """Return follow-up scheduling context."""
        return {
            "followup_fields": [
                {
                    "id": "next_awv_date",
                    "label": "Next AWV due date (earliest eligible)",
                    "type": "date",
                    "required": True,
                    "default": self._next_awv_default_date(),
                },
                {
                    "id": "next_awv_timeframe",
                    "label": "Schedule next Annual Wellness Visit",
                    "type": "select",
                    "options": [
                        {"value": "12", "label": "12 months (standard)"},
                        {"value": "6", "label": "6 months (if concerns identified)"},
                        {"value": "custom", "label": "Custom date"},
                    ],
                },
                {
                    "id": "primary_care_followup",
                    "label": "Primary care follow-up needed",
                    "type": "radio",
                    "options": ["Yes - within 2 weeks", "Yes - within 1 month", "Yes - within 3 months", "No"],
                },
                {
                    "id": "followup_reason",
                    "label": "Follow-up reason / instructions",
                    "type": "textarea",
                    "placeholder": "Describe the reason for follow-up and any patient instructions.",
                },
                {
                    "id": "pending_labs",
                    "label": "Labs / studies ordered today needing follow-up",
                    "type": "textarea",
                    "placeholder": "List any pending results that need review at follow-up.",
                },
                {
                    "id": "patient_goals",
                    "label": "Patient-stated health goals for next year",
                    "type": "textarea",
                    "placeholder": "Document any goals the patient expressed for the coming year.",
                },
            ],
            "task_options": [
                "Call patient with lab results",
                "Schedule specialist referral",
                "Confirm advance directive on file",
                "Follow up on smoking cessation",
                "Blood pressure recheck",
                "Medication reconciliation review",
            ],
            "awv_type": self.awv_type,
            "note_id": self.note_id,
        }
