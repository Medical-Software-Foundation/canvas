from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates.utils import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.appointment import Appointment


class DoxyMeTelehealthLaunchActionButton(ActionButton):
    BUTTON_TITLE = "Launch Meeting"
    BUTTON_KEY = "LAUNCH_MEETING"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def get_doxy_link(self, note_id: int) -> str | None:
        note = Note.objects.get(dbid=note_id)
        appointment = Appointment.objects.filter(note=note).order_by("-dbid").first()

        if appointment and appointment.note_type.is_telehealth:
            meeting_link = (
                appointment.meeting_link
                or appointment.provider.personal_meeting_room_link
            )
            if meeting_link and meeting_link.startswith("https://doxy.me/"):
                return meeting_link

        return None

    def visible(self) -> bool:
        note_id = self.event.context["note_id"]
        return self.get_doxy_link(note_id) is not None

    def handle(self) -> list:
        content = render_to_string("templates/meeting_template.html", {})

        return [
            LaunchModalEffect(
                content=content,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            ).apply()
        ]
