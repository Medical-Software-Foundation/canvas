"""Vitals module."""

from __future__ import annotations

from typing import Any

from canvas_sdk.v1.data.observation import Observation

from guided_awv.modules.base import AWVType, BaseModule


class VitalsModule(BaseModule):
    """
    Vitals section - height, weight, BMI (auto-calculated), blood pressure,
    heart rate. Primarily completed by staff before provider sees patient.
    """

    ORDER = 6
    TITLE = "Vitals"
    AWV_TYPES = AWVType.BOTH
    ICON = "fa-heartbeat"

    def render_content_html(self) -> str:
        """Render vitals with recent values and input fields."""
        ctx = self.get_context()
        html = ""
        # BMI counseling flag (CMS requires counseling documentation when BMI >= 30)
        bmi_value = ctx.get("bmi_value")
        if bmi_value is not None and bmi_value >= 30:
            html += self._alert(
                f"BMI is {bmi_value:.1f} (≥ 30). CMS requires documentation of "
                "obesity counseling including dietary and exercise guidance. "
                "Consider referral to nutrition/weight management.",
                "warning",
            )
        html += self._subtitle("Recent Vitals (from Chart)")
        for field in ctx["vitals_fields"]:
            recent = field.get("recent_value")
            label = f"{field['label']} ({field.get('unit', '')})"
            html += self._info_row(label, str(recent) if recent is not None else "No recent value")
        html += self._divider()
        html += self._subtitle("Enter New Vitals")
        html += (
            '<div id="bmi-calc-alert" class="awv-alert awv-alert--warning" style="display:none;">'
            '</div>'
        )
        for field in ctx["vitals_fields"]:
            label = f"{field['label']} ({field.get('unit', '')})"
            html += self._number_input(
                field["id"], label, step=field.get("step", ""),
                readonly=field.get("readonly", False),
                required=field.get("required", False),
            )
            # Insert BP arm/position after heart rate
            if field["id"] == "heart_rate":
                html += self._radio_group(
                    "bp_arm", "BP measured on which arm?", ["Left", "Right"],
                    required=True,
                )
                html += self._radio_group(
                    "bp_position", "BP patient position", ["Seated", "Standing", "Supine"],
                    required=True,
                )

        # BMI category display
        html += (
            '<div id="bmi-category" class="awv-info-row" style="margin-top:6px;">'
            '<span class="awv-info-label">BMI Category</span>'
            '<span class="awv-info-value" id="bmi-category-value">--</span>'
            '</div>'
        )
        return f'<div class="awv-module-content">{html}{self._save_button("saveVitals", "Save Vitals")}</div>'

    def get_context(self) -> dict[str, Any]:
        """Return vitals context with most recent values."""
        recent_vitals = self._get_recent_vitals()
        bmi_raw = recent_vitals.get("bmi")
        try:
            bmi_value = float(bmi_raw) if bmi_raw is not None else None
        except (ValueError, TypeError):
            bmi_value = None

        return {
            "bmi_value": bmi_value,
            "vitals_fields": [
                {
                    "id": "height",
                    "label": "Height",
                    "unit": "in",
                    "type": "number",
                    "step": "0.1",
                    "recent_value": recent_vitals.get("height"),
                    "required": True,
                },
                {
                    "id": "weight",
                    "label": "Weight",
                    "unit": "lbs",
                    "type": "number",
                    "step": "0.1",
                    "recent_value": recent_vitals.get("weight"),
                    "required": True,
                },
                {
                    "id": "bmi",
                    "label": "BMI",
                    "unit": "kg/m²",
                    "type": "number",
                    "step": "0.1",
                    "readonly": True,
                    "note": "Auto-calculated from height and weight",
                    "recent_value": recent_vitals.get("bmi"),
                },
                {
                    "id": "systolic_bp",
                    "label": "Systolic BP",
                    "unit": "mmHg",
                    "type": "number",
                    "step": "1",
                    "recent_value": recent_vitals.get("systolic_bp"),
                    "required": True,
                },
                {
                    "id": "diastolic_bp",
                    "label": "Diastolic BP",
                    "unit": "mmHg",
                    "type": "number",
                    "step": "1",
                    "recent_value": recent_vitals.get("diastolic_bp"),
                    "required": True,
                },
                {
                    "id": "heart_rate",
                    "label": "Heart Rate",
                    "unit": "bpm",
                    "type": "number",
                    "step": "1",
                    "recent_value": recent_vitals.get("heart_rate"),
                },
            ],
            "note_id": self.note_id,
        }

    def _get_recent_vitals(self) -> dict[str, Any]:
        """Fetch most recent vital observations for this patient."""
        # LOINC codes for common vitals
        loinc_map = {
            "8302-2": "height",       # Body height
            "29463-7": "weight",      # Body weight
            "39156-5": "bmi",         # BMI
            "8480-6": "systolic_bp",  # Systolic BP
            "8462-4": "diastolic_bp", # Diastolic BP
            "8867-4": "heart_rate",   # Heart rate
        }

        # Single query: fetch all matching observations, newest first.
        # REVIEW.md "Always check": filter entered-in-error so a vitals reading
        # the clinician flagged as wrong doesn't get prefilled as "Last reading".
        all_obs = (
            Observation.objects.filter(
                patient__id=self.patient_id,
                codings__code__in=loinc_map.keys(),
                codings__system="http://loinc.org",
                deleted=False,
                entered_in_error_id__isnull=True,
            )
            .order_by("-effective_datetime")
            .values("codings__code", "value")
        )

        # Keep only the most recent observation per LOINC code
        vitals: dict[str, Any] = {}
        seen_codes: set[str] = set()
        for row in all_obs:
            code = row["codings__code"]
            if code not in seen_codes and code in loinc_map:
                seen_codes.add(code)
                vitals[loinc_map[code]] = row["value"]
                if len(seen_codes) == len(loinc_map):
                    break

        return vitals
