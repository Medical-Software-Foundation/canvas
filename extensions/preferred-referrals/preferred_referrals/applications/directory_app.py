"""Provider-menu app that opens the preferred-referrals directory and report."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from preferred_referrals import CACHE_BUST


class PreferredReferralsApp(Application):
    """Opens the directory page full screen."""

    def on_open(self) -> Effect:
        """Launch the page served by ``DirectoryAPI``."""
        return LaunchModalEffect(
            url=f"/plugin-io/api/preferred_referrals/app/?v={CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
