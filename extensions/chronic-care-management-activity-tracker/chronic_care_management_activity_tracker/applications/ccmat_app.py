from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CcmatApp(Application):
    """An embeddable application that can be registered to Canvas."""

    def on_open(self) -> Effect:
        """Handle the on_open event."""
        # Implement this method to handle the application on_open event.
        patient_id = self.event.context.get("patient", {}).get("id", None)

        return LaunchModalEffect(
            title="Chronic Care Management Activity Tracker",
            url=f"/plugin-io/api/chronic_care_management_activity_tracker/{patient_id}/app",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        ).apply()
