from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class MyPanelApp(Application):
    """Global companion app that opens the logged-in provider's patient panel."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/provider_my_panel_companion/app/",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
