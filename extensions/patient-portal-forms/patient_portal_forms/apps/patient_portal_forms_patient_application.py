from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application

from logger import log

class PatientPortalFormsPatientApplication(Application):
    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url=f"/plugin-io/api/patient_portal_forms/patient-view/patient/{self.event.context['user']['id']}",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
