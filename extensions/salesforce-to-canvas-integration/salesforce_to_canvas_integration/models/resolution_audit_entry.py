"""Append only decision log for operator resolutions.

Sits beside :class:`IncomingPatientRecord`. Every time an operator resolves a
row, accept, skip, apply a modify, or any delete resolution, exactly one entry
lands here and is never edited. ``IncomingPatientRecord.status`` stays a fast
cache of the current resolution state, this table is the source of truth for
who acted, when, and what. See journal cnv-909 entries 088 and 089.

``event_id`` holds the ``IncomingPatientRecord`` primary key of the resolved
event as a plain integer rather than a Django foreign key. A foreign key from
one custom model to another can trip the sandbox DDL pipeline, and the write
site always holds the primary key, so the link is free without it. ``external_id``
and ``action`` are denormalized so a history read needs no join.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import (
    DateTimeField,
    Index,
    IntegerField,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel


class ResolutionAuditEntry(CustomModel):
    # which Salesforce record and which inbound event was resolved
    external_id: TextField[str, str] = TextField()
    event_id: IntegerField[int, int] = IntegerField()
    action: TextField[str, str] = TextField()           # create, modify, delete

    # what the operator did
    action_taken: TextField[str, str] = TextField()     # created, skipped, modify_applied, ...

    # who acted, name captured at write time so history stays readable later
    staff_key: TextField[str, str] = TextField(default="")
    staff_name: TextField[str, str] = TextField(default="")

    # when
    created_at: DateTimeField[str | datetime, datetime] = DateTimeField(auto_now_add=True)

    # optional context
    note: TextField[str, str] = TextField(default="")
    result_patient_id: TextField[str, str] = TextField(default="")
    # field level before and after, present only when the operator edited the
    # payload before saving. Stays empty until a later story populates it.
    edits: JSONField[dict[str, Any], dict[str, Any]] = JSONField(default=dict)
    # the linked Canvas patient demographics captured the instant before an apply
    # wrote, in the compare shape the Activity Details table renders. Present only
    # on a modify apply, which had a patient before the write. Empty for a create
    # from scratch and a promote, which had no prior patient, and for every non
    # writing resolution. Forward only, rows written before this field existed
    # stay empty. See journal cnv-928/036 and 037.
    canvas_before: JSONField[dict[str, Any], dict[str, Any]] = JSONField(default=dict)

    class Meta:
        indexes = [
            Index(fields=["external_id", "-created_at"]),
            Index(fields=["event_id"]),
            Index(fields=["staff_key"]),
            Index(fields=["-created_at"]),
        ]
