"""Homepage handler for BLH Schedule View.

Sets the BLH Schedule View as the default landing page for providers
when they log in or click the home icon.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.default_homepage import DefaultHomepageEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class ScheduleHomepage(BaseHandler):
    """Sets the Schedule View app as the default Canvas homepage."""

    RESPONDS_TO = EventType.Name(EventType.GET_HOMEPAGE_CONFIGURATION)

    def compute(self) -> list[Effect]:
        return [
            DefaultHomepageEffect(
                application_identifier="blh_schedule_view.applications.schedule_app:ScheduleViewApp"
            ).apply()
        ]
