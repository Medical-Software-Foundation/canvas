from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Recomputed each time the plugin loads (every deploy/reload). Appended to the modal URL so a redeploy
# changes the iframe src and the browser fetches the freshly-rendered admin page, not a cached copy.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class GoogleCalendarAdmin(Application):
    """Admin app to map Canvas staff to Workspace calendars and monitor Google sync health."""

    def on_open(self) -> Effect:
        """Open the admin UI in a modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/gcal_sync/google/admin?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
