"""FaxLabel, one row per label on a fax, per Section 3 of SPEC.md.

A fax carries several labels rather than one, so the label cannot live as a
field on FaxRecord any more. It becomes a row of its own, and who set it and
when travel on that row rather than beside a single foreign key, because those
two facts belong to one labelling rather than to the fax.

The relation points at the task proxy rather than at FaxRecord. Labelling a fax
is independent of noting one and of assigning one, so a fax that has only ever
been labelled needs no FaxRecord row, and deleting the note and the assignment
would never take the labels with it.

The unique constraint is what makes adding a label idempotent. The same label
cannot land on the same fax twice, so the add route may be replayed and the
picker never has to defend against a double click.
"""

from __future__ import annotations

from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, UniqueConstraint

from fax_queue_inboxes.models.practice_label import PracticeLabel
from fax_queue_inboxes.models.proxies import IntegrationTaskProxy, StaffProxy

from canvas_sdk.v1.data.base import CustomModel


class FaxLabel(CustomModel):
    task = ForeignKey(
        IntegrationTaskProxy, to_field="dbid", on_delete=DO_NOTHING, related_name="fax_labels"
    )
    label = ForeignKey(PracticeLabel, to_field="dbid", on_delete=DO_NOTHING, related_name="+")
    set_by = ForeignKey(StaffProxy, to_field="dbid", on_delete=DO_NOTHING, null=True, related_name="+")
    set_at = DateTimeField(null=True)

    class Meta:
        constraints = [UniqueConstraint(fields=["task", "label"], name="uq_faxlabel_task_label")]
