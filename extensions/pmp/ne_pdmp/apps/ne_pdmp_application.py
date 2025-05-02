from canvas_sdk.effects import Effect
from canvas_sdk.handlers.application import Application
from canvas_sdk.effects.launch_modal import LaunchModalEffect


class NEPDMPApplication(Application):
    def on_open(self) -> Effect:
        return LaunchModalEffect(url=f"https://secure.cynchealth.org/",
            target=LaunchModalEffect.TargetType.NEW_WINDOW).apply()
