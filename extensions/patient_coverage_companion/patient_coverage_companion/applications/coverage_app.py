from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class CoverageCompanionApp(Application):
    """Patient-scope companion app: launches the coverage editor iframe."""

    def on_open(self) -> Effect:
        patient_id = self.event.context.get("patient", {}).get("id", "")
        return LaunchModalEffect(
            url=f"/plugin-io/api/patient_coverage_companion/app/?patient_id={patient_id}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
