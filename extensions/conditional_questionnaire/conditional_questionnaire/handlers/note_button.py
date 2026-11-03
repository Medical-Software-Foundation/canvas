from datetime import UTC, datetime
from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note

from conditional_questionnaire.handlers.api import BASE_PATH

# Changes on every deploy or restart, so the pane never shows a stale page.
_CACHE_BUST = str(int(datetime.now(UTC).timestamp()))


class ConditionalQuestionnaireButton(ActionButton):
    """Note header button that opens the conditional questionnaire form beside the note."""

    BUTTON_TITLE = "Conditional Questionnaire"
    BUTTON_KEY = "CONDITIONAL_QUESTIONNAIRE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        """Offer the button on notes that can still be edited, so locked notes don't show it."""
        note_dbid = self.event.context.get("note_id")
        if note_dbid is None:
            return False
        state = CurrentNoteStateEvent.objects.filter(note_id=note_dbid).first()
        # No state row means nothing has locked the note; the save endpoint treats it the same.
        return state is None or state.editable()

    def handle(self) -> list[Effect]:
        """Open the form in the right chart pane for the note the button was clicked on."""
        note_dbid = self.event.context.get("note_id")
        if note_dbid is None:
            return []
        note_id = Note.objects.filter(dbid=note_dbid).values_list("id", flat=True).first()
        if note_id is None:
            return []
        query = urlencode({"note_id": str(note_id), "v": _CACHE_BUST})
        return [
            LaunchModalEffect(
                url=f"{BASE_PATH}/form?{query}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Conditional Questionnaire",
            ).apply()
        ]
