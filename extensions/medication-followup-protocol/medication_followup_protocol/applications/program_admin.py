"""The practice configuration page."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from medication_followup_protocol.api.routes import page


class ProgramAdmin(Application):
    """Where a practice builds its medication classes and the steps inside them."""

    def on_open(self) -> Effect:
        """Open the configuration page, which needs no patient open."""
        return LaunchModalEffect(
            url=page("/admin"),
            target=LaunchModalEffect.TargetType.PAGE,
            title="Follow Up Programs",
        ).apply()
