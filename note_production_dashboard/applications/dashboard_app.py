from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class NoteProductionDashboardApp(Application):
    """Provider menu item that opens the note production dashboard as a full page."""

    def on_open(self) -> Effect:
        """Open the dashboard as a full-page view when the menu item is clicked."""
        return LaunchModalEffect(
            url="/plugin-io/api/note_production_dashboard/dashboard",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
