"""Pre-Visit Brief companion application."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PreVisitBriefApp(Application):
    """Global companion app that opens the Pre-Visit Brief modal.

    Surfaces a stack of prep cards (up to 3) for the logged-in provider's
    upcoming appointments today, ordered by arrival time.
    """

    def on_open(self) -> Effect:
        """Launch the pre-visit brief modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/pre_visit_brief/app/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Pre-Visit Brief",
        ).apply()
