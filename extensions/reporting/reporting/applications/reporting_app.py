"""Global Application that launches the Reporting workspace full-page."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ReportingApp(Application):
    """Launches the Reporting SPA as a full-page modal from the app drawer."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/reporting/app/home",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Reporting",
        ).apply()
