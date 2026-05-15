from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_chart_summary_custom_section import PatientChartSummaryCustomSection
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from canvas_sdk.templates import render_to_string

from hospitalization_tracker.models import Hospitalization


class HospitalizationSummarySection(PatientChartSummaryCustomSectionHandler):
    """Renders the inpatient stay history in the patient chart summary."""

    SECTION_KEY = "hospitalization_history"

    def handle(self) -> list[Effect]:
        """Return the rendered hospitalization history section."""
        hospitalizations = list(
            Hospitalization.objects.filter(patient__id=self.event.target.id).order_by("-admission_date")
        )
        content = render_to_string(
            "templates/chart_summary_section.html",
            {"hospitalizations": hospitalizations},
        )
        return [
            PatientChartSummaryCustomSection(
                content=content,
                icon="🏥",
            ).apply()
        ]
