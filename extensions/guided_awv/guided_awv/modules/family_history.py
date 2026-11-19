"""Family History module."""

from __future__ import annotations

from typing import Any

from guided_awv.modules.base import AWVType, BaseModule


class FamilyHistoryModule(BaseModule):
    """Family History section - review/update family medical history."""

    ORDER = 4
    TITLE = "Family History"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-users"

    # Common family history conditions for structured capture
    COMMON_CONDITIONS = [
        "Heart Disease / CAD",
        "Hypertension",
        "Diabetes (Type 1 or 2)",
        "Stroke",
        "Cancer (specify type)",
        "Hyperlipidemia / High Cholesterol",
        "Osteoporosis",
        "Dementia / Alzheimer's",
        "Mental Health Disorders",
        "Kidney Disease",
    ]

    FAMILY_MEMBERS = [
        "Mother",
        "Father",
        "Maternal Grandmother",
        "Maternal Grandfather",
        "Paternal Grandmother",
        "Paternal Grandfather",
        "Sibling(s)",
        "Child(ren)",
    ]

    def render_content_html(self) -> str:
        """Render family history form."""
        ctx = self.get_context()
        html = ""
        html += self._alert(ctx["instructions"], "info")
        for member in ctx["family_members"]:
            member_id = member.lower().replace(" ", "_").replace("(", "").replace(")", "")
            html += self._radio_group(
                f"fhx_{member_id}_status",
                f"{member} - Status",
                ["Living", "Deceased", "Unknown"],
                required=member in ("Mother", "Father"),
            )
            html += self._number_input(
                f"fhx_{member_id}_age",
                f"{member} - Age (or age at death)",
                min_val="0",
                max_val="120",
            )
            html += self._checkbox_group(f"fhx_{member_id}", member + " - Conditions", ctx["common_conditions"])
        html += self._divider()
        html += self._textarea(
            "fhx_additional", "Additional family history notes",
            placeholder="Document any other family history not captured above.",
        )
        return f'<div class="awv-module-content">{html}{self._save_button("saveFamilyHistory", "Save Family History")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return family history context data."""
        return {
            "is_initial": self.awv_type == AWVType.INITIAL,
            "common_conditions": self.COMMON_CONDITIONS,
            "family_members": self.FAMILY_MEMBERS,
            "instructions": (
                "Review the patient's family history. "
                "For initial visits, capture all known history. "
                "For subsequent visits, ask about any changes or new diagnoses in family members."
            ),
        }
