from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PatientChartSchedulingWithRoomsApp(Application):
    """Patient-chart application that opens the scheduling modal pre-populated with the current patient."""

    def on_open(self) -> Effect:
        patient_id = self.event.context.get("patient", {}).get("id", "")
        url = f"/plugin-io/api/scheduling_with_rooms/modal?v={_CACHE_BUST}"
        if patient_id:
            url = f"{url}&patient_id={patient_id}"
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Schedule Appointment",
        ).apply()
