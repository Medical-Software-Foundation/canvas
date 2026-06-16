from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string


class RxDashboard(Application):
    """Dashboard showing prescriptions and e-prescribing statuses across all patients."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            content=render_to_string("templates/rx_dashboard.html"),
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
