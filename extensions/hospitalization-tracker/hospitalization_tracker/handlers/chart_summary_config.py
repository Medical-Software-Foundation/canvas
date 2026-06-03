from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class HospitalizationChartSummaryConfig(BaseHandler):
    """Registers the Inpatient Stay History section in the chart summary layout."""

    RESPONDS_TO = [EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)]

    def compute(self) -> list[Effect]:
        """Return the chart summary configuration with hospitalization_history first."""
        Section = PatientChartSummaryConfiguration.Section
        return [
            PatientChartSummaryConfiguration(
                sections=[
                    PatientChartSummaryConfiguration.CustomSection(name="hospitalization_history"),
                    Section.SOCIAL_DETERMINANTS,
                    Section.GOALS,
                    Section.CONDITIONS,
                    Section.MEDICATIONS,
                    Section.ALLERGIES,
                    Section.CARE_TEAMS,
                    Section.VITALS,
                    Section.IMMUNIZATIONS,
                    Section.SURGICAL_HISTORY,
                    Section.FAMILY_HISTORY,
                    Section.CODING_GAPS,
                ]
            ).apply()
        ]
