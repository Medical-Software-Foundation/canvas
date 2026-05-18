from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class IntakePanelApp(Application):
    """Embeddable application that launches the Intake Assignment Panel."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/intake_assignment_panel/app/",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
