"""Custom data model recording which failed-fax rows staff have dismissed."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import DateTimeField, TextField, UniqueConstraint


class FaxDismissal(CustomModel):
    """One dismissed row on the failed-fax dashboard.

    ``source_type`` is the row's item type key (for example ``note`` or
    ``received_fax``) and ``source_id`` is the id of the failed record: the
    action event for a sent fax, or the Fax for a received fax.

    ``closed_task_id`` is the task the dismissal closed, so a restore reopens only that
    one. Dismissals saved before the field existed read it as empty (None).
    """

    source_type: TextField = TextField()
    source_id: TextField = TextField()
    dismissed_by: TextField = TextField()
    dismissed_at: DateTimeField = DateTimeField()
    closed_task_id: TextField = TextField(default="", null=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["source_type", "source_id"], name="uq_faxdismissal_source"),
        ]
