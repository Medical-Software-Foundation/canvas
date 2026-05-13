from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication

PLUGIN_API_BASE = "/plugin-io/api/voice_dictation"


class DictateApp(NoteApplication):
    """Note tab application for voice dictation of HPI and Plan commands."""

    NAME = "Dictate"
    IDENTIFIER = "voice_dictation__dictate"
    PRIORITY = 10

    def open_by_default(self) -> bool:
        return True

    def on_open(self) -> Effect | list[Effect]:
        note_uuid = self.event.context.get("note", {}).get("id", "")
        url = f"{PLUGIN_API_BASE}/dictate/app?note_id={note_uuid}"

        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.NOTE,
            title="Dictate",
        ).apply()
