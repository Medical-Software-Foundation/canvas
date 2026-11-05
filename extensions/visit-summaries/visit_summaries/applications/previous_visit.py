"""NoteApplication tab for Previous Visit Summary."""
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication

from visit_summaries.helpers.config_store import is_feature_enabled
from visit_summaries.helpers.note_queries import get_most_recent_locked_note


class PreviousVisitApp(NoteApplication):
    """Tab showing an AI-generated summary of the patient's most recent prior locked note."""

    NAME = "Previous Visit"
    IDENTIFIER = "visit_summaries__previous_visit"

    def visible(self) -> bool:
        if not is_feature_enabled("enable_previous_visit"):
            return False
        patient_id = self.event.target.id
        note_id = self.event.context.get("note_id", "") or None
        return get_most_recent_locked_note(patient_id, exclude_note_id=note_id) is not None

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        note_id = self.event.context.get("note_id", "")
        url = (
            f"/plugin-io/api/visit_summaries/summary/previous-visit"
            f"?note_id={note_id}&patient_id={patient_id}"
        )
        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.NOTE,
                url=url,
                title="Previous Visit Summary",
            ).apply()
        ]
