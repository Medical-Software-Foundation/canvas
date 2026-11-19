from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ScheduleViewApp(Application):
    """Global companion app that renders a richer schedule view.

    Surfaces appointment type, labels (with color), provider, room, and status
    in a single-page calendar view without requiring the user to click into each
    appointment individually.
    """

    def on_open(self) -> Effect:
        """Open the schedule view modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/schedule_view/schedule/view?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
