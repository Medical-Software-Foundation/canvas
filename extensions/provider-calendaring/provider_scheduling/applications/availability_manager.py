from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class AvailabilityManager(Application):
    """An application to manage availability calendars."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        # Implement this method to handle the application on_open event.
        return LaunchModalEffect(
            url="/plugin-io/api/provider_scheduling/app/availability-app",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
