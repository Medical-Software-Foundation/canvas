"""Shared resolution writer over the two custom data models.

A captured row is resolved the same way whether a logged in operator acts on it
through the status API or the automatic apply path in the webhook acts on it.
The row's ``status`` is flipped and stamped, and one append only
:class:`ResolutionAuditEntry` is written. The only difference between the two
callers is the actor, a logged in staff member for a manual resolution and a
fixed automation actor for an auto applied sync. This module owns that shared
shape so the two callers can never drift. See journal cnv-938/030 and 033.

The clock is passed in rather than read here, so a queryset update never has to
rely on ``auto_now`` and the callers stay deterministic under test.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from salesforce_to_canvas_integration.models import (
    IncomingPatientRecord,
    ResolutionAuditEntry,
)

# The name stamped on an automatically applied sync. No staff session backs it,
# so the staff key is empty and the foreign key is null, but the name reads as a
# stable label in the Activity ledger so an operator can tell the automation
# apart from a person at a glance.
AUTOMATIC_STAFF_NAME = "Automatic sync"


@dataclass(frozen=True)
class ResolutionActor:
    """Who resolved a row. An empty actor is tolerated end to end.

    ``staff_key`` is the raw session key and ``staff_dbid`` the StaffProxy dbid
    for the row foreign key, both empty for the automation actor. ``staff_name``
    is captured at write time so the decision log stays readable later.
    """

    staff_key: str = ""
    staff_dbid: int | None = None
    staff_name: str = ""


# The singleton actor every auto applied sync resolves under.
AUTOMATIC_ACTOR = ResolutionActor(staff_name=AUTOMATIC_STAFF_NAME)


def write_resolution(
    row: IncomingPatientRecord,
    *,
    status: str,
    action_taken: str,
    actor: ResolutionActor,
    now: datetime,
    extra_fields: dict[str, Any] | None = None,
    note: str = "",
    result_patient_id: str = "",
    canvas_before: dict[str, Any] | None = None,
) -> None:
    """Resolve a row and append one decision log entry in the same step.

    The status update carries the resolution slot plus any per path typed
    columns in ``extra_fields``, and the log entry captures who acted, when, and
    what. ``canvas_before`` is the chart snapshot a modify apply took before it
    wrote, empty for every other resolution.
    """
    update_fields: dict[str, Any] = {
        "status": status,
        "actioned_at": now,
        "actioned_by_id": actor.staff_dbid,
    }
    if extra_fields:
        update_fields.update(extra_fields)
    IncomingPatientRecord.objects.filter(pk=row.pk).update(**update_fields)

    append_decision(
        row,
        action_taken=action_taken,
        actor=actor,
        note=note,
        result_patient_id=result_patient_id,
        canvas_before=canvas_before,
    )


def append_decision(
    row: IncomingPatientRecord,
    *,
    action_taken: str,
    actor: ResolutionActor,
    note: str = "",
    result_patient_id: str = "",
    canvas_before: dict[str, Any] | None = None,
) -> None:
    """Write one append only decision log entry for a row transition.

    Split from :func:`write_resolution` so a transition that clears the row
    resolution stamp rather than setting it, such as reopen, can still record
    who acted and when.
    """
    ResolutionAuditEntry.objects.create(
        external_id=row.external_id,
        event_id=row.pk,
        action=row.action,
        action_taken=action_taken,
        staff_key=actor.staff_key,
        staff_name=actor.staff_name,
        note=note,
        result_patient_id=str(result_patient_id or ""),
        canvas_before=canvas_before or {},
    )


__all__ = (
    "AUTOMATIC_ACTOR",
    "AUTOMATIC_STAFF_NAME",
    "ResolutionActor",
    "append_decision",
    "write_resolution",
)
