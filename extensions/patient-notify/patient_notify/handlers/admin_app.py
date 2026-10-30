"""Admin application for notification campaign configuration."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class NotifyAdminApp(Application):
    """Global admin application for notification campaign configuration."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch admin configuration page."""
        url = "/plugin-io/api/patient_notify/admin"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
