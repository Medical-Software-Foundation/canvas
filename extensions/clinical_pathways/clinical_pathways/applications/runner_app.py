from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PathwayRunnerApp(NoteApplication):
    """Note-tab entry point for the pathway runner SPA."""

    NAME = "Clinical Pathways"
    IDENTIFIER = "clinical_pathways__runner"
    PRIORITY = 50

    def on_open(self) -> Effect:
        # CustomCommand.note_uuid requires the external UUID string available
        # at context["note"]["id"]; context["note_id"] is the integer DB ID
        # and must not be used here.
        note_uuid = self.event.context["note"]["id"]
        patient_id = self.event.context.get("patient", {}).get("id", "")
        return LaunchModalEffect(
            url=(
                "/plugin-io/api/clinical_pathways/runner/"
                f"?note_uuid={note_uuid}&patient_id={patient_id}&v={_CACHE_BUST}"
            ),
            target=LaunchModalEffect.TargetType.NOTE,
            title="Clinical Pathways",
        ).apply()
