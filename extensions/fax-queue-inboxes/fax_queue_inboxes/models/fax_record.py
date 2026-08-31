"""FaxRecord, the plugin's own note and assignment per fax task, per Section 3 of SPEC.md.

The label used to live here as a single foreign key with its own set by and set
at beside it. A fax carries several labels now, so each one is a FaxLabel row of
its own and those three fields are gone from here. The columns themselves stay
in the database, because the platform's DDL only ever creates and adds and has
no path that drops a column, so a stale column nobody writes to is the normal
end state of removing a field rather than a sign something went wrong.
"""

from __future__ import annotations

from django.db.models import DO_NOTHING, DateTimeField, ForeignKey, OneToOneField, TextField

from fax_queue_inboxes.models.proxies import IntegrationTaskProxy, StaffProxy, TeamProxy

from canvas_sdk.v1.data.base import CustomModel


class FaxRecord(CustomModel):
    task = OneToOneField(
        IntegrationTaskProxy, to_field="dbid", on_delete=DO_NOTHING,
        related_name="fax_record", primary_key=True,
    )
    note = TextField(blank=True, default="")
    note_written_by = ForeignKey(StaffProxy, to_field="dbid", on_delete=DO_NOTHING, null=True, related_name="+")
    note_written_at = DateTimeField(null=True)
    assigned_team = ForeignKey(TeamProxy, to_field="dbid", on_delete=DO_NOTHING, null=True, related_name="+")
    assigned_staff = ForeignKey(StaffProxy, to_field="dbid", on_delete=DO_NOTHING, null=True, related_name="+")
    assigned_by = ForeignKey(StaffProxy, to_field="dbid", on_delete=DO_NOTHING, null=True, related_name="+")
    assigned_at = DateTimeField(null=True)
