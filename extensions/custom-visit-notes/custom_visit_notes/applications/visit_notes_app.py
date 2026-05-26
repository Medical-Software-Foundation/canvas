from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication

PLUGIN_API_BASE = "/plugin-io/api/custom_visit_notes"
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class VisitNotesApp(NoteApplication):
    """Note tab for free-text visit notes saved to custom data."""

    IDENTIFIER = "custom_visit_notes__tab"
    NAME = "Visit Notes"
    PRIORITY = 10

    def visible(self) -> bool:
        return True

    def open_by_default(self) -> bool:
        return False

    def on_open(self) -> Effect | list[Effect]:
        note_uuid = self.event.context.get("note", {}).get("id", "")
        tab_name = self.secrets.get("tab_name", "Visit Notes")
        url = f"{PLUGIN_API_BASE}/notes/app?note_id={note_uuid}&tab_name={tab_name}&v={_CACHE_BUST}"

        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.NOTE,
            title=tab_name,
        ).apply()
