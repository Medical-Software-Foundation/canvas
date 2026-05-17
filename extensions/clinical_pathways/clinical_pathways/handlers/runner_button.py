from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note

_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PathwayRunnerButton(ActionButton):
    """Note-header button that opens the clinical pathway runner in a side panel.

    The button shows for editable notes. On click it launches the runner SPA in
    the right chart pane, passing the note's external UUID + patient UUID so the
    SPA can POST `/complete` and originate the Q&A + recommendation custom
    commands back onto this note.
    """

    BUTTON_TITLE = "Clinical Pathways"
    BUTTON_KEY = "CLINICAL_PATHWAYS_RUNNER"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    # Editable note states: NEW=Created, PSH=Pushed, ULK=Unlocked, RST=Restored,
    # UND=Undeleted, CVD=Converted.
    _EDITABLE_NOTE_STATES = {"NEW", "PSH", "ULK", "RST", "UND", "CVD"}

    def visible(self) -> bool:
        note_id = self.context.get("note_id")
        if not note_id:
            return False
        try:
            state_event = CurrentNoteStateEvent.objects.get(note__dbid=note_id)
        except CurrentNoteStateEvent.DoesNotExist:
            return False
        return state_event.state in self._EDITABLE_NOTE_STATES

    def handle(self) -> list[Effect]:
        note_id = self.context.get("note_id")
        patient_id = self.target or ""
        try:
            note = Note.objects.get(dbid=note_id)
        except Note.DoesNotExist:
            return []
        note_uuid = note.id
        url = (
            "/plugin-io/api/clinical_pathways/runner/"
            f"?note_uuid={note_uuid}&patient_id={patient_id}&v={_CACHE_BUST}"
        )
        return [
            LaunchModalEffect(
                url=url,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
                title="Clinical Pathways",
            ).apply()
        ]
