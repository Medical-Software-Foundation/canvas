"""Functional Ability / ADLs module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class FunctionalAbilityModule(BaseModule):
    """
    Functional Ability / Activities of Daily Living (ADLs) section.

    Assesses both basic ADLs (self-care) and instrumental ADLs (independent living).
    Identifies areas where the patient may need additional support or referrals.
    """

    ORDER = 12
    TITLE = "Functional Ability / ADLs"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-hands-helping"

    ADL_ITEMS = [
        {"id": "adl_bathing", "label": "Bathing / showering"},
        {"id": "adl_dressing", "label": "Dressing"},
        {"id": "adl_grooming", "label": "Grooming / personal hygiene"},
        {"id": "adl_toileting", "label": "Toileting"},
        {"id": "adl_transferring", "label": "Transferring (bed to chair, etc.)"},
        {"id": "adl_continence", "label": "Continence"},
        {"id": "adl_eating", "label": "Feeding / eating"},
    ]

    IADL_ITEMS = [
        {"id": "iadl_phone", "label": "Using the telephone"},
        {"id": "iadl_shopping", "label": "Shopping"},
        {"id": "iadl_food_prep", "label": "Food preparation"},
        {"id": "iadl_housekeeping", "label": "Housekeeping"},
        {"id": "iadl_laundry", "label": "Laundry"},
        {"id": "iadl_transportation", "label": "Transportation"},
        {"id": "iadl_medications", "label": "Managing medications"},
        {"id": "iadl_finances", "label": "Managing finances"},
    ]

    FUNCTION_OPTIONS = [
        {"value": "independent", "label": "Independent"},
        {"value": "needs_assistance", "label": "Needs some assistance"},
        {"value": "dependent", "label": "Dependent"},
        {"value": "na", "label": "N/A"},
    ]

    def render_content_html(self) -> str:
        """Render ADL/IADL assessment grid."""
        ctx = self.get_context()
        html = ""
        html += self._subtitle("Basic Activities of Daily Living (ADLs)")
        for item in ctx["adl_items"]:
            html += self._radio_group(item["id"], item["label"], ctx["function_options"])
        html += self._divider()
        html += self._subtitle("Instrumental ADLs (IADLs)")
        for item in ctx["iadl_items"]:
            html += self._radio_group(item["id"], item["label"], ctx["function_options"])
        html += self._divider()
        for field in ctx["additional_fields"]:
            ftype = field.get("type", "text")
            required = field.get("required", False)
            if ftype == "textarea":
                html += self._textarea(field["id"], field["label"], placeholder=field.get("placeholder", ""), required=required)
            elif ftype == "checkboxes":
                html += self._checkbox_group(field["id"], field["label"], field.get("options", []), required=required)
        return f'<div class="awv-module-content">{html}{self._save_button("saveFunctionalAbility", "Save Functional Ability")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return functional ability context."""
        return {
            "adl_items": self.ADL_ITEMS,
            "iadl_items": self.IADL_ITEMS,
            "function_options": self.FUNCTION_OPTIONS,
            "additional_fields": [
                {
                    "id": "home_safety_concerns",
                    "label": "Home safety concerns identified",
                    "type": "textarea",
                    "placeholder": "Describe any home safety issues (e.g., fall hazards, stair access, medication storage).",
                },
                {
                    "id": "referrals_needed",
                    "label": "Referrals / services recommended",
                    "type": "checkboxes",
                    "options": [
                        "Occupational Therapy",
                        "Physical Therapy",
                        "Home Health Aide",
                        "Meals on Wheels",
                        "Social Work",
                        "Transportation Services",
                    ],
                },
            ],
            "note_id": self.note_id,
        }
