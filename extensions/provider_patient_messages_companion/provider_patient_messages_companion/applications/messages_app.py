from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class MessagesApp(Application):
    """Global companion app that opens live patient-message threads."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/provider_patient_messages_companion/app/",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()


class PatientMessagesApp(Application):
    """Patient-scoped companion app that opens directly to the conversation."""

    def on_open(self) -> Effect:
        patient = self.event.context.get("patient", {})
        patient_id = patient.get("id", "")
        return LaunchModalEffect(
            url=(
                "/plugin-io/api/provider_patient_messages_companion/app/"
                f"?patient_id={patient_id}"
            ),
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
