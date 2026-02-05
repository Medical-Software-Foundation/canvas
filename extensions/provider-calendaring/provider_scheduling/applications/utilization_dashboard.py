from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class UtilizationDashboard(Application):
    """An application to display schedule utilization metrics."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        return LaunchModalEffect(
            url="/plugin-io/api/provider_scheduling/app/utilization-dashboard",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
