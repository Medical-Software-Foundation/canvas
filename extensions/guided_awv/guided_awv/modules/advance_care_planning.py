"""Advance Care Planning module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class AdvanceCarePlanningModule(BaseModule):
    """
    Advance Care Planning section.

    Documents advance directives discussion, healthcare proxy designation,
    and patient preferences for end-of-life care. CMS-required component
    of the Annual Wellness Visit.
    """

    ORDER = 15
    TITLE = "Advance Care Planning"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-file-contract"

    def render_content_html(self) -> str:
        """Render advance care planning discussion form."""
        ctx = self.get_context()
        html = ""
        html += self._alert(ctx["billing_note"], "info")
        for field in ctx["discussion_fields"]:
            conditional_on = field.get("conditional_on")
            conditional_value = field.get("conditional_value")
            if conditional_on:
                html += (
                    f'<div class="awv-conditional" '
                    f'data-conditional-on="{conditional_on}" '
                    f'data-conditional-value="{conditional_value}" '
                    f'style="display:none;">'
                )
            ftype = field.get("type", "text")
            freq = field.get("required", False)
            if ftype == "radio":
                html += self._radio_group(field["id"], field["label"], field["options"], required=freq)
            elif ftype == "text":
                html += self._text_input(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=freq)
            elif ftype == "textarea":
                html += self._textarea(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=freq)
            elif ftype == "checkboxes":
                html += self._checkbox_group(field["id"], field["label"], field.get("options", []), required=freq)
            elif ftype == "number":
                html += self._number_input(field["id"], field["label"], readonly=field.get("readonly", False), required=freq)
            if conditional_on:
                html += '</div>'
        return f'<div class="awv-module-content">{html}{self._save_button("saveAdvanceCarePlanning", "Save ACP")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return advance care planning context."""
        return {
            "discussion_fields": [
                {
                    "id": "acp_discussed",
                    "label": "Was advance care planning discussed with the patient?",
                    "type": "radio",
                    "options": ["Yes", "No", "Patient declined discussion"],
                    "required": True,
                },
                # Time documentation (conditional on acp_discussed=Yes)
                {
                    "id": "acp_start_time",
                    "label": "ACP discussion start time",
                    "type": "text",
                    "placeholder": "HH:MM",
                    "conditional_on": "acp_discussed",
                    "conditional_value": "Yes",
                },
                {
                    "id": "acp_end_time",
                    "label": "ACP discussion end time",
                    "type": "text",
                    "placeholder": "HH:MM",
                    "conditional_on": "acp_discussed",
                    "conditional_value": "Yes",
                },
                {
                    "id": "acp_total_minutes",
                    "label": "Total ACP discussion time (minutes)",
                    "type": "number",
                    "readonly": True,
                    "conditional_on": "acp_discussed",
                    "conditional_value": "Yes",
                },
                # Code status
                {
                    "id": "code_status",
                    "label": "Current code status",
                    "type": "radio",
                    "options": [
                        "Full Code",
                        "DNR",
                        "DNI",
                        "DNR/DNI",
                        "Comfort Care Only",
                    ],
                },
                {
                    "id": "advance_directive_exists",
                    "label": "Does the patient have an existing advance directive on file?",
                    "type": "radio",
                    "options": ["Yes - on file", "Yes - patient has copy", "No", "Unknown"],
                    "required": True,
                },
                {
                    "id": "advance_directive_type",
                    "label": "Type of advance directive",
                    "type": "checkboxes",
                    "options": [
                        "Living Will",
                        "Healthcare Power of Attorney (HCPOA)",
                        "POLST / MOLST",
                        "DNR Order",
                        "Other",
                    ],
                    "conditional_on": "advance_directive_exists",
                    "conditional_value": "Yes - on file",
                },
                {
                    "id": "healthcare_proxy_name",
                    "label": "Healthcare proxy / surrogate decision-maker name",
                    "type": "text",
                    "placeholder": "Full name",
                },
                {
                    "id": "healthcare_proxy_relationship",
                    "label": "Relationship to patient",
                    "type": "text",
                    "placeholder": "e.g., Spouse, Adult child",
                },
                {
                    "id": "healthcare_proxy_contact",
                    "label": "Healthcare proxy contact information",
                    "type": "text",
                    "placeholder": "Phone number and/or email",
                },
                {
                    "id": "healthcare_proxy_designated",
                    "label": "Patient formally designated a healthcare proxy?",
                    "type": "radio",
                    "options": ["Yes", "No"],
                },
                # Topics discussed (conditional on acp_discussed=Yes)
                {
                    "id": "acp_topics_discussed",
                    "label": "Topics discussed during ACP",
                    "type": "checkboxes",
                    "options": [
                        "Values and goals explored",
                        "End-of-life scenarios discussed",
                        "Preferences documented",
                        "Surrogate decision-maker identified",
                        "Hospice/palliative care discussed",
                    ],
                    "conditional_on": "acp_discussed",
                    "conditional_value": "Yes",
                },
                {
                    "id": "patient_wishes_summary",
                    "label": "Summary of patient's expressed wishes / goals of care",
                    "type": "textarea",
                    "placeholder": "Document key preferences discussed (e.g., resuscitation, mechanical ventilation, hospice preferences).",
                },
                # Documents completed today (conditional on acp_discussed=Yes)
                {
                    "id": "documents_completed_today",
                    "label": "Documents completed today",
                    "type": "checkboxes",
                    "options": [
                        "Living Will",
                        "Healthcare Power of Attorney (HCPOA)",
                        "POLST / MOLST",
                        "DNR Order",
                    ],
                    "conditional_on": "acp_discussed",
                    "conditional_value": "Yes",
                },
                {
                    "id": "copy_given_to_patient",
                    "label": "Copy of documents given to patient?",
                    "type": "radio",
                    "options": ["Yes", "No", "N/A"],
                },
                {
                    "id": "documents_scanned_to_chart",
                    "label": "Documents scanned to chart?",
                    "type": "radio",
                    "options": ["Yes", "No", "N/A"],
                },
                {
                    "id": "acp_followup_needed",
                    "label": "Follow-up action needed",
                    "type": "checkboxes",
                    "options": [
                        "Provide advance directive forms",
                        "Refer to social worker",
                        "Schedule ACP counseling visit",
                        "Scan existing directive into chart",
                        "No action needed",
                    ],
                },
            ],
            "billing_note": (
                "Medicare covers voluntary advance care planning during AWV. "
                "Document time spent: 30 min face-to-face (CPT 99497) or "
                "additional 30 min (CPT 99498)."
            ),
            "note_id": self.note_id,
        }
