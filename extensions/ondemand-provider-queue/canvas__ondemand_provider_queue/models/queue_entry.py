"""Queue entries stored in Canvas custom data, one row per visit request."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DateTimeField, Index, TextField, UniqueConstraint


class QueueEntryRecord(CustomModel):
    """One on-demand visit request.

    One row per request (not one shared document), so two providers changing
    different entries never overwrite each other, and claims use a conditional
    update so only one provider can win a given entry.
    """

    entry_id = TextField()
    patient_id = TextField()
    reason_for_visit = TextField(default="")
    priority = TextField(default="routine")
    # Optional id from the sending system. Unique when present, so a retried
    # request returns the existing entry instead of making a second one.
    external_id = TextField(null=True)
    practice_location_id = TextField(null=True)
    status = TextField(default="awaiting_assignment")
    assigned_provider_id = TextField(null=True)
    assigned_provider_name = TextField(null=True)
    note_id = TextField(null=True)
    created_at = DateTimeField()
    updated_at = DateTimeField()

    class Meta:
        constraints = [  # noqa: RUF012 (Django Meta convention)
            UniqueConstraint(fields=["entry_id"], name="uq_odpq_entry_id"),
            UniqueConstraint(fields=["external_id"], name="uq_odpq_external_id"),
        ]
        indexes = [  # noqa: RUF012
            Index(fields=["status"]),
            Index(fields=["patient_id", "status"]),
            Index(fields=["note_id"]),
        ]
