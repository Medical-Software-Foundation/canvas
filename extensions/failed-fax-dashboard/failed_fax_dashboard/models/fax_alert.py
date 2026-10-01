"""Custom data behind the automatic failed-fax tasks."""

from canvas_sdk.v1.data.base import CustomModel
from django.db.models import BooleanField, DateTimeField, TextField, UniqueConstraint


class FaxAlert(CustomModel):
    """The one task for an item and fax number, and how far the scheduled job has handled it.

    ``source_type`` is the item type key (``note``, ``referral``, ... or ``received_fax``).
    ``item_id`` is the item's id (the Fax id for a received fax) and ``fax_number`` is in
    E.164 form. ``assignee`` is ``staff:<id>`` or ``team:<id>``.
    """

    source_type: TextField = TextField()
    item_id: TextField = TextField()
    fax_number: TextField = TextField()
    task_id: TextField = TextField()
    last_handled_event_id: TextField = TextField()
    last_handled_at: DateTimeField = DateTimeField()
    assignee: TextField = TextField(default="")
    closed: BooleanField = BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["source_type", "item_id", "fax_number"], name="uq_faxalert_item_number"
            ),
        ]


class AlertStart(CustomModel):
    """When the scheduled job first ran, and when it last ran.

    Failures that arrived before ``started_at`` get no task. Each run reads only what
    changed since ``last_run_at`` (less a small overlap), so a run's work stays small
    however long the plugin has been installed.
    """

    started_at: DateTimeField = DateTimeField()
    last_run_at: DateTimeField = DateTimeField(null=True)
