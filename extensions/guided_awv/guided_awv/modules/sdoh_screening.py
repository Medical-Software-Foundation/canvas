"""Social Determinants of Health (SDOH) Screening module (CMS Element 9)."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class SDOHScreeningModule(BaseModule):
    """
    Social Determinants of Health screening section.

    Covers CMS-required SDOH domains: housing, food, transportation,
    social support, safety/elder abuse, substance use, urinary
    incontinence, and pain assessment.
    """

    ORDER = 11
    TITLE = "Social Determinants of Health (SDOH)"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-home"

    SECTION_ALERTS: dict[str, tuple[str, str]] = {
        "housing": ("sdoh-housing-alert", "Positive housing instability screen. Consider referral to social work or community housing resources."),
        "utility_needs": ("sdoh-utility-alert", "Positive utility needs concern. Consider referral to LIHEAP, utility assistance programs, or social work."),
        "food": ("sdoh-food-alert", "Positive food insecurity screen. Consider referral to nutrition assistance programs (SNAP, food banks, Meals on Wheels)."),
        "transportation": ("sdoh-transportation-alert", "Positive transportation barrier. Consider referral to community transportation services or medical transport programs."),
        "social_support": ("sdoh-social-alert", "Positive social isolation screen. Consider referral to community engagement programs, senior centers, or behavioral health."),
        "safety": ("sdoh-safety-alert", "Positive safety concern. Consider referral to Adult Protective Services, domestic violence resources, or social work."),
        "substance_use": ("sdoh-substance-alert", "Positive substance use screen. Consider referral to substance abuse counseling or behavioral health."),
        "incontinence": ("sdoh-incontinence-alert", "Positive incontinence screen. Consider urology referral or pelvic floor therapy."),
        "pain": ("sdoh-pain-alert", "Positive pain screen. Consider pain management referral or further evaluation."),
    }

    def render_content_html(self) -> str:
        """Render SDOH screening form with all required domains."""
        ctx = self.get_context()
        html = ""

        html += self._alert(
            "Screen for social determinants that may affect health outcomes. "
            "CMS requires assessment of psychosocial risks and functional status. "
            "Positive screens should trigger referral or care coordination.",
            "info",
        )

        html += self._select(
            "sdoh_tool_used",
            "SDOH Screening Tool Used",
            ["PRAPARE", "AHC-HRSN", "Custom / Practice-specific", "Other"],
            required=True,
        )
        html += self._divider()

        for section in ctx["screening_sections"]:
            html += self._subtitle(section["label"])
            for field in section["fields"]:
                conditional_on = field.get("conditional_on")
                conditional_value = field.get("conditional_value")
                if conditional_on:
                    html += (
                        f'<div class="awv-conditional" '
                        f'data-conditional-on="{conditional_on}" '
                        f'data-conditional-value="{conditional_value}" '
                        f'style="display:none;">'
                    )

                ftype = field.get("type", "radio")
                freq = field.get("required", False)
                if ftype == "radio":
                    html += self._radio_group(field["id"], field["label"], field["options"], required=freq)
                elif ftype == "number":
                    html += self._number_input(
                        field["id"],
                        field["label"],
                        min_val=field.get("min", ""),
                        max_val=field.get("max", ""),
                        required=freq,
                    )
                elif ftype == "textarea":
                    html += self._textarea(
                        field["id"],
                        field["label"],
                        placeholder=field.get("placeholder", ""),
                        required=freq,
                    )

                if conditional_on:
                    html += "</div>"

            # Per-domain hidden alert div
            alert_info = self.SECTION_ALERTS.get(section["id"])
            if alert_info:
                alert_id, alert_text = alert_info
                html += (
                    f'<div id="{alert_id}" class="awv-alert awv-alert--warning" '
                    f'style="display:none;">{alert_text}</div>'
                )

            html += self._divider()

        # Overall SDOH summary (shown when any domain is positive)
        html += '<div id="sdoh-referral-section" style="display:none;">'
        html += self._divider()
        html += self._subtitle("Positive Screens & Referral Plan")
        html += '<div id="sdoh-positive-summary" class="awv-alert awv-alert--warning"></div>'
        html += self._textarea(
            "sdoh_referral_plan",
            "Referral / care coordination plan",
            placeholder="Document referrals made, community resources identified, or care coordination actions taken.",
        )
        html += '</div>'

        return f'<div class="awv-module-content">{html}{self._save_button("saveSDOHScreening", "Save SDOH Screening")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return SDOH screening context with all domains."""
        return {
            "screening_sections": self._get_screening_sections(),
            "note_id": self.note_id,
        }

    def _get_screening_sections(self) -> list[dict[str, Any]]:
        """Return all SDOH screening sections with questions."""
        return [
            {
                "id": "housing",
                "label": "Housing Stability",
                "fields": [
                    {
                        "id": "sdoh_housing_worried",
                        "label": "In the past 12 months, were you worried or concerned about losing your housing?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                        "required": True,
                    },
                    {
                        "id": "sdoh_housing_conditions",
                        "label": "Do you have problems with any of the following in your home: pests, mold, lead paint, lack of heat, lack of working stove/oven, water leaks?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                    },
                ],
            },
            {
                "id": "utility_needs",
                "label": "Utility Needs",
                "fields": [
                    {
                        "id": "sdoh_utility_concerns",
                        "label": "In the past 12 months, has the electric, gas, oil, or water company threatened to shut off services in your home?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                    },
                    {
                        "id": "sdoh_utility_details",
                        "label": "If yes, please describe",
                        "type": "textarea",
                        "placeholder": "Describe utility concerns (electricity, gas, water, heating, etc.).",
                        "conditional_on": "sdoh_utility_concerns",
                        "conditional_value": "Yes",
                    },
                ],
            },
            {
                "id": "food",
                "label": "Food Security",
                "fields": [
                    {
                        "id": "sdoh_food_worry",
                        "label": "Within the past 12 months, you worried that food would run out before you had money to buy more.",
                        "type": "radio",
                        "options": ["Often true", "Sometimes true", "Never true"],
                        "required": True,
                    },
                    {
                        "id": "sdoh_food_didnt_last",
                        "label": "Within the past 12 months, the food you bought just didn't last and you didn't have money to get more.",
                        "type": "radio",
                        "options": ["Often true", "Sometimes true", "Never true"],
                    },
                ],
            },
            {
                "id": "transportation",
                "label": "Transportation",
                "fields": [
                    {
                        "id": "sdoh_transportation",
                        "label": "In the past 12 months, has lack of reliable transportation kept you from medical appointments, meetings, work, or from getting things needed for daily living?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                        "required": True,
                    },
                ],
            },
            {
                "id": "social_support",
                "label": "Social Isolation & Support",
                "fields": [
                    {
                        "id": "sdoh_social_contact",
                        "label": "How often do you have contact (visits, phone, email) with friends or family?",
                        "type": "radio",
                        "options": ["Daily", "Weekly", "Monthly", "Rarely", "Never"],
                        "required": True,
                    },
                    {
                        "id": "sdoh_loneliness",
                        "label": "How often do you feel lonely or isolated?",
                        "type": "radio",
                        "options": ["Never", "Rarely", "Sometimes", "Often", "Always"],
                    },
                ],
            },
            {
                "id": "safety",
                "label": "Safety / Elder Abuse Screening",
                "fields": [
                    {
                        "id": "sdoh_feel_safe",
                        "label": "Do you feel physically and emotionally safe where you currently live?",
                        "type": "radio",
                        "options": ["Yes", "No", "Prefer not to answer"],
                        "required": True,
                    },
                    {
                        "id": "sdoh_afraid_partner",
                        "label": "Within the last year, have you been afraid of a partner, family member, or caregiver?",
                        "type": "radio",
                        "options": ["Yes", "No", "Prefer not to answer"],
                    },
                ],
            },
            {
                "id": "substance_use",
                "label": "Other Substance Use",
                "fields": [
                    {
                        "id": "sdoh_recreational_drugs",
                        "label": "In the past 12 months, have you used any recreational or non-prescribed drugs (including marijuana)?",
                        "type": "radio",
                        "options": ["Yes", "No", "Prefer not to answer"],
                    },
                    {
                        "id": "sdoh_substance_details",
                        "label": "If yes, please describe",
                        "type": "textarea",
                        "placeholder": "Substance(s), frequency, and any concerns.",
                        "conditional_on": "sdoh_recreational_drugs",
                        "conditional_value": "Yes",
                    },
                ],
            },
            {
                "id": "incontinence",
                "label": "Urinary Incontinence",
                "fields": [
                    {
                        "id": "sdoh_urinary_leakage",
                        "label": "In the past 3 months, have you leaked urine (even a small amount)?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                    },
                    {
                        "id": "sdoh_incontinence_frequency",
                        "label": "How often do you experience leakage?",
                        "type": "radio",
                        "options": ["Rarely", "Sometimes", "Often", "Daily"],
                        "conditional_on": "sdoh_urinary_leakage",
                        "conditional_value": "Yes",
                    },
                ],
            },
            {
                "id": "pain",
                "label": "Pain Assessment",
                "fields": [
                    {
                        "id": "sdoh_pain_present",
                        "label": "Are you currently experiencing pain?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                    },
                    {
                        "id": "sdoh_pain_scale",
                        "label": "Pain level (0 = no pain, 10 = worst possible)",
                        "type": "number",
                        "min": "0",
                        "max": "10",
                        "conditional_on": "sdoh_pain_present",
                        "conditional_value": "Yes",
                    },
                    {
                        "id": "sdoh_pain_location",
                        "label": "Pain location and description",
                        "type": "textarea",
                        "placeholder": "Describe location, quality, duration, and aggravating/alleviating factors.",
                        "conditional_on": "sdoh_pain_present",
                        "conditional_value": "Yes",
                    },
                ],
            },
        ]
