from __future__ import annotations

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication
from canvas_sdk.v1.data.note import Note

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class HospitalizationTrackerApp(NoteApplication):
    """Note application tab for adding a new hospitalization to the current note."""

    NAME = "Add Hospitalization"
    IDENTIFIER = "hospitalization_tracker__add"

    def on_open(self) -> Effect:
        """Launch the hospitalization form modal for the current patient and note."""
        patient_id = self.event.context.get("patient", {}).get("id", "")
        note_dbid = self.event.context.get("note_id")
        note = Note.objects.get(dbid=note_dbid)
        return LaunchModalEffect(
            url=(
                f"/plugin-io/api/hospitalization_tracker/app/form"
                f"?patient_id={patient_id}&note_id={note.id}&v={_CACHE_BUST}"
            ),
            target=LaunchModalEffect.TargetType.NOTE,
            title="Add Hospitalization",
        ).apply()
