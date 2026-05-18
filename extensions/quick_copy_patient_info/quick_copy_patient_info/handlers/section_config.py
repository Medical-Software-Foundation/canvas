"""Register the 'Patient Info' custom section in the patient chart summary.

Canvas only emits PATIENT_CHART_SUMMARY__GET_CUSTOM_SECTION for custom sections
that appear in the configured section list, so we must respond to the
configuration event with a list that includes our CustomSection at the top.

PatientChartSummaryConfiguration is all-or-nothing - emitting it overrides the
default chart summary section list. We therefore emit every standard section
member so installing this plugin does not hide any built-in sections.
"""

from canvas_sdk.effects.patient_chart_summary_configuration import (
    PatientChartSummaryConfiguration,
)
from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler


SECTION_KEY = "quick_copy_patient_info"


class QuickCopyPatientInfoSectionConfig(BaseHandler):
    """Adds the 'Patient Info' custom section to the patient chart summary."""

    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)

    def compute(self):
        Section = PatientChartSummaryConfiguration.Section
        layout = PatientChartSummaryConfiguration(
            sections=[
                PatientChartSummaryConfiguration.CustomSection(name=SECTION_KEY),
                Section.CONDITIONS,
                Section.MEDICATIONS,
                Section.ALLERGIES,
                Section.GOALS,
                Section.VITALS,
                Section.IMMUNIZATIONS,
                Section.SURGICAL_HISTORY,
                Section.FAMILY_HISTORY,
                Section.SOCIAL_DETERMINANTS,
                Section.CARE_TEAMS,
                Section.CODING_GAPS,
            ]
        )
        return [layout.apply()]
