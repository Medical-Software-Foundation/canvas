from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class PrescriptionProcessingApplication(Application):
    """Application that launches the Prescription Processing Dashboard."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/prescription_processing_dashboard/app/dashboard",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
