"""ActionButton - Generate AVS button in the note footer, opens side panel."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

from visit_summaries.helpers.config_store import is_feature_enabled


class GenerateAvsButton(ActionButton):
    """Button in the note footer that generates a patient-friendly After Visit Summary."""

    BUTTON_TITLE = "Generate AVS"
    BUTTON_KEY = "visit_summaries__generate_avs"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_FOOTER
    PLUGIN_API_BASE = "/plugin-io/api/visit_summaries/summary"

    def visible(self) -> bool:
        """Only show when the AVS feature is enabled."""
        return is_feature_enabled("enable_avs")

    def handle(self) -> list[Effect]:
        """Open the AVS panel immediately with a loading state."""
        note_id = self.event.context.get("note_id", "")
        patient_id = self.event.target.id
        url = f"{self.PLUGIN_API_BASE}/avs?note_id={note_id}&patient_id={patient_id}"
        return [
            LaunchModalEffect(
                url=url,
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
                title="After Visit Summary",
            ).apply()
        ]
