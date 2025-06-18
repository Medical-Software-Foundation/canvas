from jwt import encode
import time

from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates.utils import render_to_string
from canvas_sdk.v1.data.note import Note
from canvas_sdk.v1.data.appointment import Appointment
from canvas_sdk.v1.data.staff import Staff


class ZoomTelehealthLaunchActionButton(ActionButton):
    BUTTON_TITLE = "Launch Meeting"
    BUTTON_KEY = "LAUNCH_MEETING"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def get_zoom_link(self, note_id):
        note = Note.objects.get(dbid=note_id)
        appointment = Appointment.objects.filter(note=note).order_by('-dbid').first()

        if appointment and appointment.note_type.is_telehealth:
            meeting_link = appointment.meeting_link or appointment.provider.personal_meeting_room_link
            if "zoom.us" in meeting_link:
                return meeting_link

    def visible(self) -> bool:
        note_id = self.event.context["note_id"]
        if self.get_zoom_link(note_id):
            return True
        return False

    def generate_zoom_jwt_token(self, meeting_number):
        # issue time
        iat_time = int(time.time())

        payload = {
            "appKey": self.secrets["ZOOM_CLIENT_ID"],
            "sdkKey": self.secrets["ZOOM_CLIENT_ID"],
            "mn": meeting_number,
            "role": 1, # 0 for participant, 1 for host
            "iat": iat_time,
            "exp": iat_time + (48 * 60 * 60), # Zoom recommends 48 hours after iat_time
            "tokenExp": iat_time + (48 * 60 * 60),
            "video_webrtc_mode": 0
        }
        return encode(payload, self.secrets["ZOOM_CLIENT_SECRET"], algorithm="HS256")

    def parse_zoom_meeting_number_and_password(self, zoom_link):
        split_link = zoom_link.split("/")
        meeting_number, qs_params = split_link[4].split("?")
        meeting_password = ""
        pwd = qs_params.split("=")
        if pwd[0] == "pwd":
            meeting_password = pwd[1]
        return meeting_number, meeting_password

    def handle(self):
        note_id = self.event.context["note_id"]
        logged_in_user = self.event.context["user"]

        if logged_in_user["type"] == "Staff":
            staff_member = Staff.objects.get(id=logged_in_user["id"])
            username = f"{staff_member.first_name} {staff_member.last_name}"
        else:
            note = Note.objects.get(dbid=note_id)
            if note.provider:
                username = f"{note.provider.first_name} {note.provider.last_name}"
            else:
                username = note.location.full_name

        zoom_link = self.get_zoom_link(note_id)
        meeting_number, password = self.parse_zoom_meeting_number_and_password(zoom_link)

        zoom_jwt_signature = self.generate_zoom_jwt_token(meeting_number)

        context = {
            "sdkKey": self.secrets["ZOOM_CLIENT_ID"],
            "signature": zoom_jwt_signature,
            "meetingNumber": meeting_number,
            "passWord": password,
            "userName": username,
            "meetingHasEndedUrl": "about:blank"
        }

        content = render_to_string("templates/meeting_template.html", context)

        return [
            LaunchModalEffect(
                content=content,
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            ).apply()
        ]
