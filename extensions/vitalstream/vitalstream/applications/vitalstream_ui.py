from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates


class VitalstreamUILauncher(ActionButton):
    BUTTON_TITLE = "Record with VitalStream"
    BUTTON_KEY = "LAUNCH_VITALSTREAM"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        note_current_state = CurrentNoteStateEvent.objects.get(note__dbid=self.context["note_id"])
        if note_current_state.state == NoteStates.LOCKED:
            return False
        return True

    def handle(self) -> list[Effect]:
        # The UI handler does the get-or-create on the VitalstreamSession row.
        # ActionButton.handle() doesn't reliably commit ORM writes here — other
        # MSF plugins always persist from SimpleAPI handlers — so this button's
        # only job is to launch the UI scoped to the note.
        note_id = self.context.get("note_id")
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/vitalstream/vitalstream-ui/notes/{note_id}/",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            ).apply()
        ]
