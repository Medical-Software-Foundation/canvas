"""Append only audit row for every inbound Salesforce event.

One table holds create, update, and delete, with the action as a column. Every
event is a new row. Dedup compares the content hash against the newest row for
the same external id and action. The decision fields are written in place on the
create row when a human acts on it. See journal cnv-909 entries 028 and 030.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db.models import (
    DO_NOTHING,
    DateTimeField,
    ForeignKey,
    Index,
    JSONField,
    TextField,
)

from canvas_sdk.v1.data.base import CustomModel

from salesforce_to_canvas_integration.models.proxy import PatientProxy, StaffProxy


class IncomingPatientRecord(CustomModel):
    # where it came from
    external_id: TextField[str, str] = TextField()              # Salesforce record id
    source_object: TextField[str, str] = TextField(default="")  # Lead, Contact
    action: TextField[str, str] = TextField()                   # create, update, delete

    # what Salesforce sent
    first_name: TextField[str, str] = TextField(default="")
    last_name: TextField[str, str] = TextField(default="")
    email: TextField[str, str] = TextField(default="")
    phone: TextField[str, str] = TextField(default="")
    raw_payload: JSONField[dict[str, Any], dict[str, Any]] = JSONField(default=dict)

    # why the deliberate sync evaluator held this row for manual action, the
    # short stable reason strings from services.sync_rules. Empty on a row the
    # evaluator auto applied, and empty on rows captured before the evaluator
    # wired into the webhook. The webhook writes this in a later step. See
    # journal cnv-938/032.
    hold_reasons: JSONField[list[str], list[str]] = JSONField(default=list)

    # dedup over external id plus action plus payload
    content_hash: TextField[str, str] = TextField()

    # when the event arrived
    received_at: DateTimeField[str | datetime, datetime] = DateTimeField(auto_now_add=True)

    # human decision, written in place on the create row when audited.
    # These stay empty on inbound capture, so they are nullable. They fill in
    # only when a human converts the row. The deployed schema is nullable either
    # way because the custom data DDL pipeline strips column constraints, but the
    # Django level null lets the SQLite test database accept an inbound insert.
    status: TextField[str, str] = TextField(default="new")      # new, accepted, dismissed
    canvas_patient: ForeignKey[PatientProxy | None, PatientProxy | None] = ForeignKey(
        PatientProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="incoming_records",
        null=True,
    )
    actioned_by: ForeignKey[StaffProxy | None, StaffProxy | None] = ForeignKey(
        StaffProxy,
        to_field="dbid",
        on_delete=DO_NOTHING,
        related_name="audited_records",
        null=True,
    )
    actioned_at: DateTimeField[str | datetime | None, datetime | None] = DateTimeField(null=True)

    class Meta:
        indexes = [
            Index(fields=["external_id"]),
            Index(fields=["external_id", "action", "-received_at"]),
            Index(fields=["status"]),
            Index(fields=["-received_at"]),
        ]
