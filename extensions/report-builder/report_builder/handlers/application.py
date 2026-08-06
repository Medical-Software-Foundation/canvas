"""ReportBuilderApp — launches the SPA via LaunchModalEffect."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Cache bust: timestamp generated once at module load, changes on every deploy/restart.
# The Canvas sandbox forbids Path/json.load at runtime, so we can't read the manifest version.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ReportBuilderApp(Application):
    """App-drawer entry point for the Report Builder."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/report_builder/app?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Report Builder",
        ).apply()
