from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Stable per process lifetime. Rotates on redeploy when the module reloads.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class BulkSurescriptsApp(Application):
    """Global provider menu item for bulk Surescripts eligibility and med history requests."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/rx_history/bulk/page?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Surescripts Requests",
        ).apply()
