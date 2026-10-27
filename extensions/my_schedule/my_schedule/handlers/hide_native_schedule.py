"""Hide the native Schedule menu item and Appointments panel filter for restricted staff.

This only changes what restricted staff see by default. It is not access control:
Canvas's /schedule page still loads if someone goes to it directly.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.panel_configuration import PanelConfiguration
from canvas_sdk.effects.provider_menu_configuration import ProviderMenuConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from my_schedule.handlers.access import is_restricted, staff_by_user_dbid

Items = ProviderMenuConfiguration.Items
GlobalSection = PanelConfiguration.PanelGlobalSection


class HideNativeScheduleMenu(BaseHandler):
    """Every provider menu item except Schedule, for restricted staff."""

    RESPONDS_TO = EventType.Name(EventType.GET_PROVIDER_MENU_CONFIGURATION)

    def compute(self) -> list[Effect]:
        # The actor is the Canvas user's database id, as on the homepage event.
        staff = staff_by_user_dbid(self.event.actor.id)
        if not is_restricted(staff, self.secrets):
            return []
        items = [item for item in Items if item is not Items.SCHEDULE]
        return [ProviderMenuConfiguration(items=items).apply()]


class HideAppointmentsPanelFilter(BaseHandler):
    """Every global panel section except Appointments, for restricted staff."""

    RESPONDS_TO = EventType.Name(EventType.PANEL_SECTIONS_CONFIGURATION)

    def compute(self) -> list[Effect]:
        # The effect payload doesn't say which panel it's for, so answer only the
        # global panel. A patient chart's panel arrives with the patient as target.
        if self.event.target.id:
            return []
        staff = staff_by_user_dbid(self.event.actor.id)
        if not is_restricted(staff, self.secrets):
            return []
        sections = [s for s in GlobalSection if s is not GlobalSection.APPOINTMENT]
        return [
            PanelConfiguration(
                sections=sections, page=PanelConfiguration.Page.GLOBAL
            ).apply()
        ]
