"""Assessment & Plan module."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.condition import Condition, ClinicalStatus

from guided_awv.modules.base import AWVType, BaseModule


class AssessmentPlanModule(BaseModule):
    """
    Assessment & Plan section.

    Captures diagnoses identified during the AWV, personalized prevention plan,
    and referrals. Provider can add diagnoses directly from this section
    via DiagnoseCommand.
    """

    ORDER = 16
    TITLE = "Assessment & Plan"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-notes-medical"

    def render_content_html(self) -> str:
        """Render assessment and plan form."""
        ctx = self.get_context()
        html = ""
        html += self._subtitle(f"Active Conditions ({ctx['condition_count']})")
        if ctx["active_conditions"]:
            for c in ctx["active_conditions"]:
                display = c.get("codings__display") or "Unknown"
                code = c.get("codings__code") or ""
                html += self._info_row(display, code)
        else:
            html += '<p style="color:#999;font-size:12px;">No active conditions</p>'
        html += self._divider()
        for field in ctx["plan_fields"]:
            ftype = field.get("type", "text")
            required = field.get("required", False)
            if ftype == "textarea":
                html += self._textarea(
                    field["id"], field["label"],
                    placeholder=field.get("placeholder", ""),
                    required=required,
                )
            elif ftype == "checkboxes":
                html += self._checkbox_group(
                    field["id"], field["label"], field.get("options", []),
                    required=required,
                )
            else:
                html += self._text_input(
                    field["id"], field["label"],
                    placeholder=field.get("placeholder", ""),
                    required=required,
                )
        return f'<div class="awv-module-content">{html}{self._save_button("saveAssessmentPlan", "Save Plan")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return assessment and plan context."""
        # REVIEW.md "Always check": exclude clinician-flagged entered-in-error
        # records so they don't surface in the assessment list.
        active_conditions = self._dedup_by_id(list(
            Condition.objects.filter(
                patient__id=self.patient_id,
                clinical_status=ClinicalStatus.ACTIVE,
                deleted=False,
                entered_in_error_id__isnull=True,
            )
            .values("id", "codings__display", "codings__code")
            .order_by("codings__display")
        ))

        return {
            "active_conditions": active_conditions,
            "condition_count": len(active_conditions),
            "plan_fields": [
                {
                    "id": "prevention_plan",
                    "label": "Personalized Prevention Plan",
                    "type": "textarea",
                    "placeholder": (
                        "Document the individualized prevention plan including: "
                        "health education, counseling, and interventions provided. "
                        "Include goals discussed with the patient."
                    ),
                    "required": True,
                },
                {
                    "id": "referrals",
                    "label": "Referrals / Orders",
                    "type": "textarea",
                    "placeholder": "List any referrals placed during this visit.",
                },
                {
                    "id": "patient_education",
                    "label": "Patient Education Provided",
                    "type": "checkboxes",
                    "options": [
                        "Medication adherence",
                        "Diet / nutrition counseling",
                        "Physical activity",
                        "Smoking cessation",
                        "Fall prevention",
                        "Weight management",
                        "Chronic disease management",
                        "Cancer screening importance",
                        "Vaccine recommendations",
                    ],
                },
            ],
            "note_id": self.note_id,
        }
