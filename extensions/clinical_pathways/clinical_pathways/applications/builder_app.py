from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PathwayBuilderApp(Application):
    """Provider-menu entry point for the pathway builder SPA."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/clinical_pathways/builder/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Pathway Builder",
        ).apply()
