"""Provider menu entry that opens the note template builder."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application


class NoteTemplatesAdminApp(Application):
    """Provider menu entry for creating and editing note templates."""

    def on_open(self) -> Effect:
        """Open the builder page, served by NoteTemplatesAPI."""
        return LaunchModalEffect(
            url="/plugin-io/api/charting_tools/admin",
            target=LaunchModalEffect.TargetType.PAGE,
            title="Charting Admin",
        ).apply()
