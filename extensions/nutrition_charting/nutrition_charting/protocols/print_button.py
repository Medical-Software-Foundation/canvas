"""Note-header action button that opens the printable Nutrition Note modal."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.v1.data.note import Note
from logger import log

from nutrition_charting.applications.nutrition_charting_app import is_nutrition_note


class PrintNutritionNoteButton(ActionButton):
    """Print button shown in the note header for Nutrition note types."""

    BUTTON_TITLE = "Print Nutrition Note"
    BUTTON_KEY = "PRINT_NUTRITION_NOTE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def visible(self) -> bool:
        return is_nutrition_note(self.event.context.get("note_id"))

    def handle(self) -> list[Effect]:
        # NOTE_HEADER context delivers the note's *dbid* (small int) on both
        # `event.context["note_id"]` and `event.target.id`. The print API
        # downstream queries Note + Patient by UUID, so resolve here before
        # building the URL — otherwise the API gets "536"-style ids and the
        # downstream UUIDField validators raise.
        note_dbid = self.event.context.get("note_id") or self.event.target.id
        note_uuid = ""
        patient_uuid = ""
        if note_dbid:
            try:
                note = Note.objects.select_related("patient").get(dbid=note_dbid)
                note_uuid = str(note.id)
                if note.patient is not None:
                    patient_uuid = str(note.patient.id)
            except Note.DoesNotExist:
                log.warning(
                    f"[PrintNutritionNoteButton] Note dbid={note_dbid} not found"
                )

        url = (
            f"/plugin-io/api/nutrition_charting/print/"
            f"?patient_id={patient_uuid}&note_id={note_uuid}"
        )
        return [LaunchModalEffect(url=url).apply()]
