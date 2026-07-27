"""Collections menu item application."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class CollectionsApp(Application):
    """Provider menu item that opens the daily collections report."""

    def on_open(self) -> Effect:
        """Open the collections report in a full-page modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/collections_report/collections/report?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
