"""EHIExportApp — global-scope Application handler.

Opens the EHI export workspace as a full-page view when a staff user clicks the
app-drawer entry. The page itself is served by ExportAPI.
"""

from datetime import UTC, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Cache-bust token: generated once at module load so every deploy gets a fresh value.
# The Canvas sandbox forbids filesystem access, so we cannot read CANVAS_MANIFEST.json
# at runtime — a UTC timestamp is the correct alternative.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))


class EHIExportApp(Application):
    """Staff app-drawer entry that launches the EHI export workspace."""

    def on_open(self) -> Effect:
        """Return a full-page LaunchModalEffect pointing at the export workspace."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/ehi_export_tool/app/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="EHI & C-CDA Export",
        ).apply()
