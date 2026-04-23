from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class RegisterPatientApp(Application):
    """Global companion app: opens a modal form to register a new patient."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/provider_register_patient_companion/app/",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
