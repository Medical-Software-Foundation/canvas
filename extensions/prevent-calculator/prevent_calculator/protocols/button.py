"""Action button on the chart conditions/problem-list section.

Clicking the button launches the PREVENT calculator modal in the right
chart pane. The plugin manifest's `name` (set in CANVAS_MANIFEST.json) drives
the URL prefix used by the SimpleAPI route below.
"""

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton


class PreventCalculatorButton(ActionButton):
    """Adds a 'PREVENT CVD Score' button to the chart conditions section."""

    BUTTON_TITLE = "PREVENT CVD Score"
    BUTTON_KEY = "prevent_calculator_open"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_SUMMARY_CONDITIONS_SECTION

    def handle(self) -> list:
        patient_id = self.event.target.id
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/prevent_calculator/calculator?patient_id={patient_id}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="PREVENT CVD Risk Calculator",
            ).apply()
        ]
