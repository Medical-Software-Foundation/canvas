"""Hide the native Canvas Schedule menu item and Appointments panel filter.

When blh_schedule_view provides the full schedule experience, the native
Schedule entry in the provider hamburger menu is redundant and confusing
(staff accidentally book via the native scheduler, breaking room linkage).

Requires Canvas SDK >= 0.191.0 (ProviderMenuConfiguration effect).
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.panel_configuration import PanelConfiguration
from canvas_sdk.effects.provider_menu_configuration import ProviderMenuConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

Items = ProviderMenuConfiguration.Items
GlobalSection = PanelConfiguration.PanelGlobalSection


class HideNativeScheduleMenu(BaseHandler):
    """Hide the native Schedule item from the provider hamburger menu."""

    RESPONDS_TO = EventType.Name(EventType.GET_PROVIDER_MENU_CONFIGURATION)

    def compute(self) -> list[Effect]:
        return [
            ProviderMenuConfiguration(
                items=[
                    Items.PATIENTS,
                    Items.REVENUE,
                    Items.POPULATIONS,
                    Items.CAMPAIGNS,
                    Items.DATA_INTEGRATION,
                    Items.QUESTIONNAIRE_BUILDER,
                    Items.SETTINGS,
                    Items.MULTI_FACTOR_AUTHENTICATION,
                    Items.CHANGELOG,
                    Items.HELP_CENTER,
                ]
            ).apply()
        ]


class HideAppointmentsPanelFilter(BaseHandler):
    """Hide the Appointments filter from the global panel.

    Only applies to the global (non-patient) panel. Patient-specific
    panels are left untouched.
    """

    RESPONDS_TO = EventType.Name(EventType.PANEL_SECTIONS_CONFIGURATION)

    def compute(self) -> list[Effect]:
        return [
            PanelConfiguration(
                sections=[
                    GlobalSection.CHANGE_REQUEST,
                    GlobalSection.IMAGING_REPORT,
                    GlobalSection.INPATIENT_STAY,
                    GlobalSection.LAB_REPORT,
                    GlobalSection.MESSAGE,
                    GlobalSection.OUTSTANDING_REFERRAL,
                    GlobalSection.PRESCRIPTION_ALERT,
                    GlobalSection.RECALL_APPOINTMENT,
                    GlobalSection.REFERRAL_REPORT,
                    GlobalSection.REFILL_REQUEST,
                    GlobalSection.TASK,
                    GlobalSection.UNCATEGORIZED_DOCUMENT,
                ],
                page=PanelConfiguration.Page.GLOBAL,
            ).apply()
        ]
