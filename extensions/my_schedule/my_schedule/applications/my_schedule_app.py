from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class MyScheduleApp(Application):
    """Full-page view of the logged-in staff member's own appointments."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/my_schedule/app/",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
