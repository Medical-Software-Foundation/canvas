"""App drawer entry that opens the queue screen."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

QUEUE_URL = "/plugin-io/api/canvas__ondemand_provider_queue/routes/ui/queue"


class ProviderQueueApp(Application):
    """Opens the on-demand provider queue as a full page."""

    def on_open(self) -> Effect:
        """Open the queue screen."""
        return LaunchModalEffect(
            url=QUEUE_URL,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Provider Queue",
        ).apply()
