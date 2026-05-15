from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_chart_summary_custom_section import PatientChartSummaryCustomSection
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)


class HospitalizationSummarySection(PatientChartSummaryCustomSectionHandler):
    """Renders the inpatient stay history in the patient chart summary."""

    SECTION_KEY = "hospitalization_history"

    def handle(self) -> list[Effect]:
        """Return the URL-based chart summary section (enables live WebSocket refresh)."""
        patient_id = self.event.target.id
        return [
            PatientChartSummaryCustomSection(
                url=f"/plugin-io/api/hospitalization_tracker/section?patient_id={patient_id}",
                icon="🏥",
            ).apply()
        ]
