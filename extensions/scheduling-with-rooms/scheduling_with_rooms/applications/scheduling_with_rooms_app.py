from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Cache-bust the modal URL so reinstalls invalidate any cached HTML.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class SchedulingWithRoomsApp(Application):
    """Application handler that opens the scheduling modal."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching the scheduling modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/scheduling_with_rooms/modal?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Schedule Appointment",
        ).apply()
