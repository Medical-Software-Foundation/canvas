from urllib.parse import quote

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication
from canvas_sdk.v1.data.note import Note
from logger import log

from sleep_screening.rfv import note_matches_trigger

PLUGIN_API_BASE = "/plugin-io/api/sleep_screening"
DEFAULT_TRIGGER_CODE = "sleep-intake"


class SleepScreeningApp(NoteApplication):
    """The Sleep Screening note tab. Visible only when the note carries a
    reason-for-visit matching the configured trigger code."""

    IDENTIFIER = "sleep_screening__tab"
    NAME = "Sleep Screening"
    PRIORITY = 10

    def _trigger_code(self) -> str:
        return self.secrets.get("RFV_TRIGGER_CODE", DEFAULT_TRIGGER_CODE)

    def _note_dbid(self):
        # The application ON_GET / ON_OPEN context carries the note's integer
        # dbid under the flat "note_id" key (not a nested note dict).
        return self.event.context.get("note_id")

    def _patient_id(self) -> str:
        patient = self.event.context.get("patient") or {}
        return patient.get("id", "") or self.event.context.get("patient_id", "")

    def visible(self) -> bool:
        return note_matches_trigger(self._note_dbid(), self._trigger_code())

    def on_open(self) -> Effect | list[Effect]:
        note_dbid = self._note_dbid()
        note_uuid = ""
        patient_id = self._patient_id()
        if note_dbid:
            try:
                note = Note.objects.get(dbid=note_dbid)
                note_uuid = str(note.id)
                if not patient_id and note.patient:
                    patient_id = str(note.patient.id)
            except Note.DoesNotExist:
                log.warning("sleep_screening: note dbid not found: " + str(note_dbid))

        url = (
            PLUGIN_API_BASE
            + "/screening/app"
            + "?note_id="
            + quote(note_uuid)
            + "&patient_id="
            + quote(patient_id)
        )
        return LaunchModalEffect(
            url=url,
            target=LaunchModalEffect.TargetType.NOTE,
            title="Sleep Screening",
        ).apply()
