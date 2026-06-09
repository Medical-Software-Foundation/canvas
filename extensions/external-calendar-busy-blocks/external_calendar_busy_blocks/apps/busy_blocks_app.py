from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class BusyBlocksApplication(Application):
    """Global-scope app that launches the config modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/external_calendar_busy_blocks/pages/config",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
