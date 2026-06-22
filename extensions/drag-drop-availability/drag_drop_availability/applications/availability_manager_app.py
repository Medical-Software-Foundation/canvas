"""Provider-menu application that opens the drag-and-drop availability manager."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Bumped on every plugin install so returning staff don't open a stale modal.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class AvailabilityManagerApp(Application):
    """Provider-menu app that opens the availability manager UI."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/drag_drop_availability/app/availability-app?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Manage Availability",
        ).apply()
