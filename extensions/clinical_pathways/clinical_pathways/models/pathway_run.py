from canvas_sdk.v1.data.base import CustomModel
from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
)

from clinical_pathways.models.pathway import Pathway


class PathwayRun(CustomModel):
    """One in-progress execution of a pathway, scoped to a single note.

    Created when the provider picks a pathway from the note-header picker.
    `current_step_id` tracks which step in the pathway's `definition.steps`
    list is waiting on a committed interview response; the runtime evaluator
    advances it as `INTERVIEW_UPDATED` events fire. `inserted_questionnaires`
    records which Canvas questionnaire ids have already been originated into
    the note so the evaluator doesn't double-insert.

    Legacy v0.3 column `current_node_id` is retained in the table (SDK does
    not permit drops) but is no longer written by v0.4 code.
    """

    note_uuid = TextField()
    pathway = ForeignKey(
        Pathway,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="runs",
    )
    # v0.3 vestige; not written in v0.4.
    current_node_id = TextField(default="")
    # v0.4 additions
    current_step_id = TextField(default="")
    inserted_questionnaires = JSONField(default=list)
    # Questionnaires for which an INTERVIEW_UPDATED event has fired with a
    # committer set. Used to distinguish "we inserted this but the user
    # hasn't committed it yet" from "user committed but skipped this
    # specific question." Once committed, a step whose question wasn't
    # answered is treated as answered-blank and the pathway advances.
    committed_questionnaires = JSONField(default=list)
    status = TextField(default="active")  # "active" | "completed"
    captured_responses = JSONField(default=dict)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            Index(fields=["note_uuid"]),
            Index(fields=["status"]),
            Index(fields=["note_uuid", "status"]),
        ]
