from __future__ import annotations

from urllib.parse import urlencode

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, Note

# Note states a provider can still edit: new, pushed, unlocked, restored, undeleted, converted.
EDITABLE_NOTE_STATES = {"NEW", "PSH", "ULK", "RST", "UND", "CVD"}


class DotPhrasesButton(ActionButton):
    """Note-header button that opens the Dot Phrases chart panel."""

    BUTTON_TITLE = "Dot Phrases"
    BUTTON_KEY = "DOT_PHRASES_PANEL"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        note_id = self.context.get("note_id")
        if not note_id:
            return False
        state = CurrentNoteStateEvent.objects.filter(note__dbid=note_id).values_list("state", flat=True).first()
        return state in EDITABLE_NOTE_STATES

    def handle(self) -> list[Effect]:
        note_uuid = Note.objects.filter(dbid=self.context.get("note_id")).values_list("id", flat=True).first()
        if note_uuid is None:
            return []
        query = urlencode({"note_id": str(note_uuid)})
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/dot_phrases/panel/?{query}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
                title="Dot Phrases",
            ).apply()
        ]
