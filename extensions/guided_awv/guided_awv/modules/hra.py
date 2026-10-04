"""Health Risk Assessment (HRA) module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class HRAModule(BaseModule):
    """
    Health Risk Assessment section.

    Initial AWV: Full initial HRA questionnaire covering health status,
    psychosocial risks, behavioral risks (tobacco, alcohol, exercise, diet,
    seatbelts), and ADL/IADL screening.

    Subsequent AWV: Update version - review and confirm changes since last AWV.
    """

    ORDER = 1
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-heart"

    @property
    def TITLE(self) -> str:  # type: ignore[override]
        """Return title based on AWV type."""
        if self.awv_type == AWVType.INITIAL:
            return "Health Risk Assessment (Initial)"
        return "Health Risk Assessment (Update)"

    def get_context(self) -> dict[str, Any]:
        """Return HRA context data."""
        return {
            "is_initial": self.awv_type == AWVType.INITIAL,
            "questionnaire_sections": self._get_questionnaire_sections(),
        }

    HRA_COMPLETION_METHODS = [
        "Mail (mailed questionnaire)",
        "Patient portal",
        "Phone",
        "In-person",
    ]

    def render_content_html(self) -> str:
        """Render HRA as proper form fields."""
        ctx = self.get_context()
        html = ""

        # HRA completion tracking (Phase 3 CMS gap closure)
        html += self._subtitle("HRA Completion Status")
        html += self._radio_group(
            "hra_completed",
            "Has the HRA been completed?",
            ["Yes", "No"],
            required=True,
        )
        html += (
            '<div class="awv-conditional" '
            'data-conditional-on="hra_completed" '
            'data-conditional-value="Yes" '
            'style="display:none;">'
        )
        html += self._select(
            "hra_completion_method",
            "How was the HRA completed?",
            self.HRA_COMPLETION_METHODS,
        )
        html += "</div>"
        html += self._textarea(
            "hra_health_concerns",
            "Patient-identified health concerns or priorities",
            placeholder="Document any health concerns the patient wants to address during this visit.",
        )
        html += self._divider()

        for section in ctx["questionnaire_sections"]:
            html += self._subtitle(section["label"])
            for field in section["fields"]:
                ftype = field.get("type", "text")
                freq = field.get("required", False)
                if ftype == "radio":
                    html += self._radio_group(field["id"], field["label"], field["options"], required=freq)
                elif ftype == "number":
                    html += self._number_input(field["id"], field["label"], required=freq)
                else:
                    html += self._text_input(field["id"], field["label"], required=freq)
                # Tobacco cessation counseling alert (hidden until "Yes" selected)
                if field["id"] == "tobacco_use":
                    html += (
                        '<div id="tobacco-alert" class="awv-alert awv-alert--warning" '
                        'style="display:none;">'
                        'Patient reports current tobacco use. CMS requires documentation '
                        'of tobacco cessation counseling (CPT 99406/99407). Discuss '
                        'cessation options, pharmacotherapy, and provide quit resources.'
                        '</div>'
                    )
            html += self._divider()
        return f'<div class="awv-module-content">{html}{self._save_button("saveHRA", "Save HRA")}</div>'

    def _get_questionnaire_sections(self) -> list[dict[str, Any]]:
        """Return questionnaire sections appropriate for AWV type."""
        common_sections: list[dict[str, Any]] = [
            {
                "id": "health_status",
                "label": "General Health Status",
                "fields": [
                    {
                        "id": "general_health",
                        "label": "How would you rate your overall health?",
                        "type": "radio",
                        "options": ["Excellent", "Very Good", "Good", "Fair", "Poor"],
                        "required": True,
                    },
                    {
                        "id": "health_change",
                        "label": "Compared to one year ago, how would you rate your health in general now?",
                        "type": "radio",
                        "options": [
                            "Much better",
                            "Somewhat better",
                            "About the same",
                            "Somewhat worse",
                            "Much worse",
                        ],
                    },
                ],
            },
            {
                "id": "behavioral_risks",
                "label": "Behavioral Risk Factors",
                "fields": [
                    {
                        "id": "tobacco_use",
                        "label": "Do you currently use tobacco products?",
                        "type": "radio",
                        "options": ["Yes", "No", "Former user"],
                    },
                    {
                        # Drives CPT II 4004F (Tobacco cessation intervention received).
                        # Without this, 4004F is unreachable - the handler reads
                        # responses['cessation_intervention'] but there'd be no input
                        # to provide it. Clinically meaningful only when tobacco_use=Yes
                        # but the question is asked unconditionally to keep the workflow
                        # simple; providers can answer N/A for non-users.
                        "id": "cessation_intervention",
                        "label": "Was tobacco cessation counseling or intervention provided today?",
                        "type": "radio",
                        "options": ["Yes", "No", "N/A"],
                    },
                    {
                        "id": "alcohol_use",
                        "label": "On average, how many alcoholic drinks do you have per week?",
                        "type": "number",
                    },
                    {
                        "id": "exercise_days",
                        "label": "How many days per week do you engage in moderate physical activity (at least 30 minutes)?",
                        "type": "number",
                    },
                    {
                        "id": "seatbelt",
                        "label": "Do you always wear a seatbelt when in a vehicle?",
                        "type": "radio",
                        "options": ["Always", "Sometimes", "Never", "N/A"],
                    },
                ],
            },
            {
                "id": "psychosocial_risks",
                "label": "Psychosocial Risks",
                "fields": [
                    {
                        "id": "social_support",
                        "label": "Do you have people in your life who provide emotional support?",
                        "type": "radio",
                        "options": ["Yes", "No", "Sometimes"],
                    },
                    {
                        "id": "caregiver_stress",
                        "label": "Are you a caregiver for a family member or friend?",
                        "type": "radio",
                        "options": ["Yes", "No"],
                    },
                    {
                        "id": "food_security",
                        "label": "In the past 12 months, did you worry that food would run out before you had money to buy more?",
                        "type": "radio",
                        "options": ["Often true", "Sometimes true", "Never true"],
                    },
                    {
                        "id": "housing_stability",
                        "label": "Do you have stable housing?",
                        "type": "radio",
                        "options": ["Yes", "No", "Unsure"],
                    },
                ],
            },
        ]

        if self.awv_type == AWVType.INITIAL:
            # Initial AWV has additional comprehensive ADL/IADL screening
            common_sections.append(
                {
                    "id": "adl_iadl",
                    "label": "Activities of Daily Living (Initial Screening)",
                    "fields": [
                        {
                            "id": "adl_bathing",
                            "label": "Bathing/showering",
                            "type": "radio",
                            "options": [
                                "Independent",
                                "Needs assistance",
                                "Dependent",
                            ],
                        },
                        {
                            "id": "adl_dressing",
                            "label": "Dressing",
                            "type": "radio",
                            "options": [
                                "Independent",
                                "Needs assistance",
                                "Dependent",
                            ],
                        },
                        {
                            "id": "adl_toileting",
                            "label": "Toileting",
                            "type": "radio",
                            "options": [
                                "Independent",
                                "Needs assistance",
                                "Dependent",
                            ],
                        },
                        {
                            "id": "iadl_medications",
                            "label": "Managing medications",
                            "type": "radio",
                            "options": [
                                "Independent",
                                "Needs assistance",
                                "Dependent",
                            ],
                        },
                        {
                            "id": "iadl_finances",
                            "label": "Managing finances",
                            "type": "radio",
                            "options": [
                                "Independent",
                                "Needs assistance",
                                "Dependent",
                            ],
                        },
                        {
                            "id": "iadl_transportation",
                            "label": "Transportation",
                            "type": "radio",
                            "options": [
                                "Independent",
                                "Needs assistance",
                                "Dependent",
                            ],
                        },
                    ],
                }
            )

        return common_sections
