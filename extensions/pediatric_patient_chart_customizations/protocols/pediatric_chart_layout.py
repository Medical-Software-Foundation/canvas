import arrow

from canvas_sdk.events import EventType
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.effects.patient_chart_summary_configuration import PatientChartSummaryConfiguration
from canvas_sdk.v1.data.patient import Patient

from logger import log


class PediatricChartLayout(BaseHandler):
    """
    This event handler rearranges the patient summary section to focus on the
    parts most relevant to pediatric patients when it detects that the patient
    for the current chart is <= 17 years old.
    """

    # This event fires when a patient chart's summary section is loading.
    RESPONDS_TO = EventType.Name(EventType.PATIENT_CHART_SUMMARY__SECTION_CONFIGURATION)

    def compute(self):
        """
        Check to see if the patient is <= 17 years old. If so, move their
        immunization list to the top of the patient summary.
        """

        eighteen_years_ago = arrow.now().shift(years=-18).date().isoformat()
        patient_is_pediatric = Patient.objects.filter(
            id=self.target, birth_date__gt=eighteen_years_ago).exists()

        # If the patient is not pediatric, do not alter the layout.
        if not patient_is_pediatric:
            return []

        layout = PatientChartSummaryConfiguration(sections=[
          PatientChartSummaryConfiguration.Section.IMMUNIZATIONS,
          PatientChartSummaryConfiguration.Section.SOCIAL_DETERMINANTS,
          PatientChartSummaryConfiguration.Section.GOALS,
          PatientChartSummaryConfiguration.Section.CONDITIONS,
          PatientChartSummaryConfiguration.Section.MEDICATIONS,
          PatientChartSummaryConfiguration.Section.ALLERGIES,
          PatientChartSummaryConfiguration.Section.CARE_TEAMS,
          PatientChartSummaryConfiguration.Section.VITALS,
          PatientChartSummaryConfiguration.Section.SURGICAL_HISTORY,
          PatientChartSummaryConfiguration.Section.FAMILY_HISTORY,
        ])

        return [layout.apply()]
