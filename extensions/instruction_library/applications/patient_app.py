"""Patient-scoped app for adding instructions to a note."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string


class PatientInstructionsApp(Application):
    def on_open(self) -> Effect:
        staff_id = self.context.get("user", {}).get("id", "")
        patient_id = self.context.get("patient", {}).get("id", "")
        return LaunchModalEffect(
            content=render_to_string(
                "templates/patient_instructions.html",
                {
                    "staff_id": staff_id,
                    "patient_id": patient_id,
                },
            ),
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()
