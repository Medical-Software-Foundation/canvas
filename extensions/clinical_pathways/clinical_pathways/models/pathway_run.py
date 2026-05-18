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
    `current_node_id` tracks which node in the pathway's `definition` tree is
    waiting on a committed interview response; the runtime evaluator advances
    it as `INTERVIEW_UPDATED` events fire. `status` flips to "completed" once
    a terminal node is originated.
    """

    note_uuid = TextField()
    pathway = ForeignKey(
        Pathway,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="runs",
    )
    current_node_id = TextField(default="")
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
