from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Changes on every plugin load, so the modal page is fetched fresh after an upgrade.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class SettingsAccessAdmin(Application):
    """Opens the page where an administrator picks which roles can see Settings."""

    def on_open(self) -> Effect:
        """Launch the configuration page in a modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/hide_settings/admin/config?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
