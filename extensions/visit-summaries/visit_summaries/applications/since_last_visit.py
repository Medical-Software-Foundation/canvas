"""NoteApplication tab for Since Your Last Visit."""
import arrow

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import NoteApplication

from visit_summaries.helpers.config_store import is_feature_enabled
from visit_summaries.helpers.note_queries import get_most_recent_locked_note, has_interim_activity


class SinceLastVisitApp(NoteApplication):
    """Tab showing interim clinical activity between the last locked visit and the current note."""

    NAME = "Since Last Visit"
    IDENTIFIER = "visit_summaries__since_last_visit"

    def visible(self) -> bool:
        if not is_feature_enabled("enable_since_last_visit"):
            return False
        patient_id = self.event.target.id
        note_id = self.event.context.get("note_id", "") or None
        prior_note = get_most_recent_locked_note(patient_id, exclude_note_id=note_id)
        if not prior_note or not prior_note.datetime_of_service:
            return False
        return has_interim_activity(
            patient_id,
            prior_note.datetime_of_service,
            arrow.now(),
        )

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        note_id = self.event.context.get("note_id", "")
        url = (
            f"/plugin-io/api/visit_summaries/summary/since-last-visit"
            f"?note_id={note_id}&patient_id={patient_id}"
        )
        return [
            LaunchModalEffect(
                target=LaunchModalEffect.TargetType.NOTE,
                url=url,
                title="Since Your Last Visit",
            ).apply()
        ]
