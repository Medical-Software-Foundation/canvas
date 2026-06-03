"""Candid dashboard application.

Full-page application launched from the Canvas provider menu. Lists all claims
that have been submitted to Candid along with their current status, last sync,
and any submission errors.

The UI (HTML/CSS/JS) lives in ``static/dashboard.*`` and is served by
``candid.api.app.CandidAppAssets``; this handler just iframes that page.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CandidDashboard(Application):
    """Full-page list view of all Candid-submitted claims with status."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/candid/app/dashboard",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Candid Dashboard",
        ).apply()
