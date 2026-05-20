"""App-drawer entry for compound_medication_loader."""

from __future__ import annotations

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string


class CompoundMedicationLoaderApp(Application):
    """Opens the CSV upload + preview modal."""

    PLUGIN_API_BASE_ROUTE = "/plugin-io/api/compound_medication_loader"

    def on_open(self) -> Effect:
        content = render_to_string(
            "templates/loader.html",
            {"api_base": self.PLUGIN_API_BASE_ROUTE},
        )
        return LaunchModalEffect(
            content=content,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
