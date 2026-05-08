"""Admin application for visit-type → room mapping configuration."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class SchedulingAdminApp(Application):
    """Provider-menu admin app for the visit-type/room matrix."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/scheduling_with_rooms/admin?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Scheduling Admin",
        ).apply()
