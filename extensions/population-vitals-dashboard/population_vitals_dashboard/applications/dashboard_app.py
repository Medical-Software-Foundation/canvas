"""PopulationDashboardApp — global-scope Application handler.

Opens the population vitals dashboard as a full-page view when the staff
user clicks the app drawer entry.  The page itself is served by DashboardAPI.
"""

from datetime import UTC, datetime

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Cache-bust token: generated once at module load so every deploy gets a fresh value.
# The Canvas sandbox forbids filesystem access, so we cannot read CANVAS_MANIFEST.json
# at runtime — a UTC timestamp is the correct alternative.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))


class PopulationDashboardApp(Application):
    """Staff app-drawer entry that launches the population vitals dashboard."""

    def on_open(self) -> Effect:
        """Return a full-page LaunchModalEffect pointing at the dashboard HTML."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/population_vitals_dashboard/app/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Population Vitals Dashboard",
        ).apply()
