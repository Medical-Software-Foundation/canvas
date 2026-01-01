from uuid import uuid4

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.command import Command
from canvas_sdk.v1.data.note import CurrentNoteStateEvent, NoteStates
from canvas_sdk.effects.launch_modal import LaunchModalEffect

from vitalstream.util import session_key

from logger import log


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
        note_id = self.context.get("note_id")

        if self.context.get('user', {}).get('type') != 'Staff':
            raise RuntimeError('Launching user must be Staff!')
        staff_id = self.context.get('user', {}).get('id')

        session_id = self.get_new_session_id(note_id, staff_id)

        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/vitalstream/vitalstream-ui/sessions/{session_id}/",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            ).apply()
        ]


    def get_new_session_id(self, note_id: str, staff_id: str) -> str:
        cache = get_cache()

        # Generate a session uuid
        session_id = str(uuid4())

        # Check to ensure it does not already exist, regenerating new
        # session_ids as needed until we generate one that does not exist.
        session_id_generation_attempts = 1
        while cache.get(session_key(session_id)) is not None:
            session_id = str(uuid4())
            session_id_generation_attempts += 1
            if session_id_generation_attempts > 10:
                raise RuntimeError("Could not generate a session identifier.")

        # Persist the session with the generated id as a cache key and the
        # note id and staff id as values.
        session_data = {
            "note_id": note_id,
            "staff_id": staff_id,
        }
        two_days_in_seconds = 60 * 60 * 24 * 2
        cache.set(session_key(session_id), session_data, timeout_seconds=two_days_in_seconds)

        return session_id
