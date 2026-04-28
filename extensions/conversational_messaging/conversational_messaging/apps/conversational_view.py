from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from logger import log

class ConversationalViewApp(Application):
    """Application handler that launches the conversational messaging view."""

    def on_open(self):
        """Open the modal anchored to the patient's chart context."""
        patient_context = self.event.context.get("patient", {})
        patient_id = patient_context.get("id")

        if patient_id is None:
            log.warning("Unable to open conversational view, missing patient id in event context")
            return []

        return LaunchModalEffect(
            url=f"/plugin-io/api/conversational_messaging/conversation/{patient_id}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Patient Messages",
        ).apply()
