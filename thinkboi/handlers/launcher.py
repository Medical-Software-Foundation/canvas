from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.events import EventType
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import Note


class GiveMeThinkboi(ActionButton):
    BUTTON_TITLE = "Thinkboi Inspo"
    BUTTON_KEY = "THINKBOI"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    RESPONDS_TO = [
        EventType.Name(EventType.SHOW_NOTE_HEADER_BUTTON),
        EventType.Name(EventType.ACTION_BUTTON_CLICKED)
    ]

    def handle(self) -> list[Effect]:
        note_id = str(Note.objects.get(dbid=self.event.context['note_id']).id)
        patient_id = self.target
        params = f"note_id={note_id}&patient_id={patient_id}"
        thinkboi_ui = LaunchModalEffect(
            url=f"/plugin-io/api/thinkboi/inspo?{params}",
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
        )
        return [thinkboi_ui.apply()]

    def visible(self) -> bool:
        return True
