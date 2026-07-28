from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Stamped at import so each deploy serves a fresh URL — the bulk page is
# fetched by the browser (unlike the chart modal, whose HTML is inlined into
# the effect), so without this a cached copy can outlive a plugin update.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class BulkSurescriptsApp(Application):
    """Global provider menu item for bulk Surescripts eligibility and med history requests."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/surescripts_med_history/bulk/page?v=%s" % _CACHE_BUST,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Surescripts Requests",
        ).apply()
