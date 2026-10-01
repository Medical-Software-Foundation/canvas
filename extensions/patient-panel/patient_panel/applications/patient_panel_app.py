from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Module-load timestamp. Changes on every deploy/restart so a fresh modal
# frame URL bypasses the browser's cache.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PatientPanelApp(Application):
    """An embeddable application that can be registered to Canvas."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/patient_panel/app/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
