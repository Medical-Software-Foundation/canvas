"""Application - global scope configuration panel for visit-summaries."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ConfigApp(Application):
    """Global scope application that opens the visit-summary configuration panel."""

    PLUGIN_API_BASE_ROUTE = "/plugin-io/api/visit_summaries"

    def on_open(self) -> Effect:
        """Launch the configuration panel."""
        save_url = f"{self.PLUGIN_API_BASE_ROUTE}/config"
        return LaunchModalEffect(
            url=f"{self.PLUGIN_API_BASE_ROUTE}/config-panel?save_url={save_url}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            title="Visit Summary Configuration",
        ).apply()
