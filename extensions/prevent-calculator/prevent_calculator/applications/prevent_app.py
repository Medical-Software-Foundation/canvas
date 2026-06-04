"""Application entry-point so PREVENT shows up in the chart Plugins tab.

Opens the same calculator modal as the conditions-section action button,
but reachable from the Plugins tab next to Consents etc.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class PreventCalculatorApp(Application):
    """Patient-scoped application that launches the PREVENT calculator."""

    def on_open(self) -> Effect:
        """Open the calculator modal pre-filled for the active patient."""
        patient_id = self.context["patient"]["id"]
        return LaunchModalEffect(
            url=f"/plugin-io/api/prevent_calculator/calculator?patient_id={patient_id}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            title="PREVENT CVD Risk Calculator",
        ).apply()
