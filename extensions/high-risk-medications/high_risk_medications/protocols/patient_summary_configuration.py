from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration


class SummarySectionLayout(BaseHandler):
    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)

    def compute(self):
        layout = PatientChartSummaryConfiguration(sections=[
          PatientChartSummaryConfiguration.Section.MEDICATIONS,
          PatientChartSummaryConfiguration.Section.SOCIAL_DETERMINANTS,
          PatientChartSummaryConfiguration.Section.GOALS,
          PatientChartSummaryConfiguration.Section.CODING_GAPS,
          PatientChartSummaryConfiguration.Section.CONDITIONS,
          PatientChartSummaryConfiguration.Section.ALLERGIES,
          PatientChartSummaryConfiguration.Section.CARE_TEAMS,
          PatientChartSummaryConfiguration.Section.VITALS,
          PatientChartSummaryConfiguration.Section.IMMUNIZATIONS,
          PatientChartSummaryConfiguration.Section.SURGICAL_HISTORY,
          PatientChartSummaryConfiguration.Section.FAMILY_HISTORY,
        ])

        return [layout.apply()]
