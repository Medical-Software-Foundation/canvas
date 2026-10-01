"""Provider-menu launcher for the Daily Readiness Dashboard.

Registered in the manifest with ``scope: provider_menu_item`` so it appears in
the provider's top menu (not the 9-dot app drawer). Opens the dashboard as a
full page, served by the SimpleAPI routes in ``routes/dashboard_api.py``.
"""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

# Full plugin-io path of the dashboard index route (see DashboardIndexRoute.PATH).
DASHBOARD_URL = "/plugin-io/api/daily_dashboard/app"


class DashboardApp(Application):
    """Opens the Daily Readiness Dashboard as a full page."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch the dashboard page."""
        return LaunchModalEffect(
            url=DASHBOARD_URL,
            target=LaunchModalEffect.TargetType.PAGE,
            title="Daily Readiness",
        ).apply()
