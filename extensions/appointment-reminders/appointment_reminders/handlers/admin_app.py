"""Global admin application for appointment reminder configuration."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class NotifyAdminApp(Application):
    """Global admin application for appointment reminder campaigns."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch the appointment reminder admin page."""
        url = f"/plugin-io/api/appointment_reminders/admin?v={_CACHE_BUST}"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Appointment Reminders",
        ).apply()
