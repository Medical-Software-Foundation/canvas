"""Open My Schedule at login for restricted staff. Everyone else keeps the normal homepage."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.default_homepage import DefaultHomepageEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler

from my_schedule.handlers.access import is_restricted, staff_by_user_dbid

APP_IDENTIFIER = "my_schedule.applications.my_schedule_app:MyScheduleApp"


class MyScheduleHomepage(BaseHandler):
    """Sets My Schedule as the homepage for restricted roles."""

    RESPONDS_TO = EventType.Name(EventType.GET_HOMEPAGE_CONFIGURATION)

    def compute(self) -> list[Effect]:
        # The homepage event's actor is the Canvas user's database id.
        staff = staff_by_user_dbid(self.event.actor.id)
        if not is_restricted(staff, self.secrets):
            return []
        return [DefaultHomepageEffect(application_identifier=APP_IDENTIFIER).apply()]
