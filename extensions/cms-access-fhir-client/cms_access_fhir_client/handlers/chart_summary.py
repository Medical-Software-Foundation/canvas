"""Custom patient chart summary section for ACCESS alignment state."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration
from canvas_sdk.effects.patient_chart_summary_custom_section import PatientChartSummaryCustomSection
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler
from canvas_sdk.handlers.patient_chart_summary_custom_section_handler import (
    PatientChartSummaryCustomSectionHandler,
)
from canvas_sdk.templates import render_to_string

from cms_access_fhir_client.models import ACCESSAlignment

SECTION_KEY = "access_alignment"


class AccessChartSummaryConfiguration(BaseHandler):
    """Registers the ACCESS alignment section in the patient chart summary layout."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)

    def compute(self) -> list[Effect]:
        if self.secrets.get("ACCESS_SHOW_CHART_SUMMARY", "").lower() != "true":
            return []

        return [
            PatientChartSummaryConfiguration(
                sections=[
                    PatientChartSummaryConfiguration.CustomSection(name=SECTION_KEY),
                    PatientChartSummaryConfiguration.Section.CONDITIONS,
                    PatientChartSummaryConfiguration.Section.MEDICATIONS,
                    PatientChartSummaryConfiguration.Section.ALLERGIES,
                    PatientChartSummaryConfiguration.Section.VITALS,
                ]
            ).apply()
        ]


class AccessChartSummarySection(PatientChartSummaryCustomSectionHandler):
    """Renders ACCESS alignment state in a custom chart summary section.

    Updates in real time via WebSocket channel access-cms_access_fhir_client-{patient_id}.
    """

    SECTION_KEY = SECTION_KEY

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id

        alignment = (
            ACCESSAlignment.objects.filter(patient__id=patient_id)
            .order_by("-updated_at")
            .first()
        )

        content = render_to_string(
            "templates/access_summary.html",
            {
                "alignment": alignment,
                "patient_id": patient_id,
            },
        )

        return [
            PatientChartSummaryCustomSection(
                content=content,
                icon="A",
            ).apply()
        ]
