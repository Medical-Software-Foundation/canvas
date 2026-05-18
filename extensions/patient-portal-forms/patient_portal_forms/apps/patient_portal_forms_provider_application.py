from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


from canvas_sdk.templates import render_to_string
from logger import log


class PatientPortalFormsProviderApplication(Application):
    def on_open(self) -> Effect | list[Effect]:
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/patient_portal_forms/provider-view/patient/{self.event.context['patient']['id']}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE
            ).apply()
        ]
