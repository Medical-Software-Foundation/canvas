"""Hide the legacy 'Note search' (COMMAND) from the patient panel.

The chart_command_search application replaces the built-in note search,
so we remove COMMAND from the patient panel sections while keeping
everything else visible.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.panel_configuration import PanelConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class HideLegacyNoteSearch(BaseHandler):
    """Remove the legacy Note search button from the patient chart panel."""

    RESPONDS_TO = EventType.Name(EventType.PANEL_SECTIONS_CONFIGURATION)

    def compute(self) -> list[Effect]:
        patient = self.target
        if not patient:
            return []

        # Include all patient panel sections EXCEPT COMMAND (legacy note search)
        return [
            PanelConfiguration(
                sections=[
                    PanelConfiguration.PanelPatientSection.CHANGE_REQUEST,
                    PanelConfiguration.PanelPatientSection.IMAGING_REPORT,
                    PanelConfiguration.PanelPatientSection.INPATIENT_STAY,
                    PanelConfiguration.PanelPatientSection.LAB_REPORT,
                    PanelConfiguration.PanelPatientSection.PRESCRIPTION_ALERT,
                    PanelConfiguration.PanelPatientSection.REFERRAL_REPORT,
                    PanelConfiguration.PanelPatientSection.REFILL_REQUEST,
                    PanelConfiguration.PanelPatientSection.TASK,
                    PanelConfiguration.PanelPatientSection.UNCATEGORIZED_DOCUMENT,
                ],
                page=PanelConfiguration.Page.PATIENT,
            ).apply()
        ]
