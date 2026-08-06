"""Patient-scoped application: this patient's appointment reminder history."""
from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class NotifyPatientApp(Application):
    """Per-patient view of appointment reminders sent, plus a manual send."""

    def on_open(self) -> Effect | list[Effect]:
        """Launch the patient's appointment reminder panel."""
        patient_id = self.event.context.get("patient", {}).get("id", "")

        url = (
            f"/plugin-io/api/appointment_reminders/patient-view"
            f"?patient_id={patient_id}&v={_CACHE_BUST}"
        )
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="Appointment Reminders",
        ).apply()
