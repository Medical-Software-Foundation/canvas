"""Patient-scoped Application that opens the Oura Ring chart drawer."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class OuraChartApp(Application):
    """Lives in the chart drawer; opens the SimpleAPI-served chart shell."""

    def on_open(self) -> Effect:
        """Launch the chart shell for the active patient."""
        patient_id = self.context["patient"]["id"]
        return LaunchModalEffect(
            url=f"/plugin-io/api/oura_ring_viewer/?patient_id={patient_id}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            title="Oura Ring",
        ).apply()
