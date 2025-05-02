from canvas_sdk.effects import Effect
from canvas_sdk.handlers.application import Application
from canvas_sdk.effects.launch_modal import LaunchModalEffect


class WIPDMPApplication(Application):
    def on_open(self) -> Effect:
        return LaunchModalEffect(url=f"https://pdmp.wi.gov/",
            target=LaunchModalEffect.TargetType.NEW_WINDOW).apply()
