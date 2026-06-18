"""Results Follow-Up Queue companion application."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class ResultsQueueApp(Application):
    """Global companion app that opens the Results Follow-Up Queue modal.

    Lists the lab and imaging results awaiting the logged-in provider's review,
    flags abnormal results, and shows how long each has been pending.
    """

    def on_open(self) -> Effect:
        """Launch the results follow-up queue modal."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/results_followup_queue/app/?v={_CACHE_BUST}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Results Follow-Up Queue",
        ).apply()
