"""Chart-Closure Queue companion application."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ChartClosureApp(Application):
    """Global companion app that opens the Chart-Closure Queue modal.

    Surfaces the logged-in provider's own open/unsigned notes that still need
    to be locked, aged oldest-first, so the documentation loop for each visit
    can be closed.
    """

    def on_open(self) -> Effect:
        """Launch the chart-closure queue modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/chart_closure_queue/app/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Chart-Closure Queue",
        ).apply()
