from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class VitalsVisualizerCompanionApp(Application):
    """Patient-scope companion launcher for the vitals visualizer.

    Emits the same LaunchModalEffect URL as VitalsVisualizerButton
    (/plugin-io/api/vitals_visualizer/?patient=<uuid>), so both the
    in-chart action button and the patient companion page surface the
    same UI served by VisualApp.
    """

    def on_open(self) -> Effect:
        patient = self.event.context.get("patient", {})
        patient_id = patient.get("id", "")
        return LaunchModalEffect(
            url=f"/plugin-io/api/vitals_visualizer/?patient={patient_id}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
