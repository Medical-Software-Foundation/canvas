from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class StaffDirectoryApp(Application):
    """Launches the staff profile directory in a full-page modal."""

    def on_open(self) -> Effect:
        return LaunchModalEffect(
            url="/plugin-io/api/staff_directory/app/directory",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Staff Directory",
        ).apply()
