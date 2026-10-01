"""App drawer entry that opens the failed-fax dashboard."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from failed_fax_dashboard.api.dashboard_api import CACHE_BUST, PAGE_URL


class FailedFaxDashboardApp(Application):
    """Opens the dashboard. The page itself enforces who may see it."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch the dashboard page."""
        return LaunchModalEffect(
            url=f"{PAGE_URL}?v={CACHE_BUST}",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Failed faxes",
        ).apply()
