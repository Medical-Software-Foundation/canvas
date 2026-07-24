"""Patient application for viewing notification history."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class NotifyPatientApp(Application):
    """Patient-specific application for viewing notification history."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch patient notification history page."""
        patient_id = self.event.context.get("patient", {}).get("id", "")

        url = f"/plugin-io/api/patient_notify/patient-view?patient_id={patient_id}"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Patient Notifications",
        ).apply()
