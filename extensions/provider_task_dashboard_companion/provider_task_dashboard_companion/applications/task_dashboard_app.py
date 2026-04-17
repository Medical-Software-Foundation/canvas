from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class TaskDashboardApp(Application):
    """Global companion app that opens a filterable task dashboard."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/provider_task_dashboard_companion/app/",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
        ).apply()
