from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CalendarLinks(Application):
    """Show the logged in user's calendar subscription links."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        return LaunchModalEffect(
            url="/plugin-io/api/ical/calendars",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
