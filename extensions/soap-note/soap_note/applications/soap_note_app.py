from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication

PLUGIN_API_BASE = "/plugin-io/api/soap_note"
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class SoapNoteApp(NoteApplication):
    """Note tab for structured SOAP charting."""

    IDENTIFIER = "soap_note__charting"
    NAME = "SOAP Charting"
    PRIORITY = 10

    def visible(self) -> bool:
        return True

    def open_by_default(self) -> bool:
        return False

    def on_open(self) -> Effect | list[Effect]:
        note_uuid = self.event.context.get("note", {}).get("id", "")
        url = f"{PLUGIN_API_BASE}/soap/app?note_id={note_uuid}&v={_CACHE_BUST}"

        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.NOTE,
            title="SOAP Charting",
        ).apply()
