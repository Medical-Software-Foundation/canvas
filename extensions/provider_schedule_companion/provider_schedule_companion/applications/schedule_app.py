from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class ScheduleApp(Application):
    """Global companion app that opens the logged-in staff member's schedule."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/provider_schedule_companion/app/",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
