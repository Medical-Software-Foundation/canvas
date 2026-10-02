"""Giving resources to a patient, and reading back what they were given."""

from datetime import datetime, timezone
from typing import Any, NamedTuple

from patient_resources.constants import (
    MAX_SHARE_BATCH,
    PORTAL_MAX_RESOURCES,
    STATUS_ACTIVE,
)
from patient_resources.models import PatientResource, PatientResourceShare


class ShareResult(NamedTuple):
    """What one send actually did.

    A NamedTuple rather than a dataclass, so this module is free to use
    ``from __future__ import annotations`` if it ever needs to -- the sandbox
    trap that breaks stringified annotations only applies to ``@dataclass``.

    All three counts are reported because a send is partially idempotent: the
    provider needs to know that two went out, one was already there, and one has
    since been archived, rather than seeing a bare success.
    """

    created: list[Any]
    already_shared: int
    skipped_unavailable: int


def live_shares_for_patient(patient_dbid: Any) -> Any:
    """The resources a patient can currently see, newest first.

    ``select_related`` because the payload now reads the live title and label
    from the catalog row, so without it every share would fetch its resource
    separately. The ``resource__status`` filter traverses the same key, and is
    what makes archiving a harmful link remove it from every patient at once.

    Ordered by ``-dbid`` as a tiebreak because ``shared_at`` is nullable and rows
    written in one batch share a timestamp -- without it the order of a
    multi-select send is arbitrary between requests.
    """
    return (
        PatientResourceShare.objects.filter(
            patient__dbid=patient_dbid,
            revoked_at__isnull=True,
            resource__status=STATUS_ACTIVE,
        )
        .select_related("resource")
        .order_by("-shared_at", "-dbid")[:PORTAL_MAX_RESOURCES]
    )


def revoked_shares_for_patient(patient_dbid: Any) -> Any:
    """Withdrawn resources, so the portal can say so rather than go quiet.

    A patient who was counselled on a handout should not find their list one item
    shorter with no explanation.
    """
    return PatientResourceShare.objects.filter(
        patient__dbid=patient_dbid,
        revoked_at__isnull=False,
    ).order_by("-revoked_at", "-dbid")[:PORTAL_MAX_RESOURCES]


def shared_resource_dbids(patient_dbid: Any, resource_dbids: list[Any]) -> set[Any]:
    """Which of these resources the patient already has, in one query.

    Used to mark rows in the picker. Deliberately a single set lookup rather than
    an ``.exists()`` per row, which is the N+1 this plugin is most likely to grow
    by accident.
    """
    if not resource_dbids:
        return set()
    return set(
        PatientResourceShare.objects.filter(
            patient__dbid=patient_dbid,
            resource__dbid__in=list(resource_dbids),
            revoked_at__isnull=True,
        ).values_list("resource_id", flat=True)
    )


def resources_with_live_shares(resource_dbids: list[Any]) -> set[Any]:
    """Which of these resources a patient currently holds.

    This is what decides whether Withdraw has anything to act on. "Has ever been
    shared" is the wrong question for that: a resource whose every share was
    already withdrawn would still offer the control, and clicking it would revoke
    nothing.

    ``distinct()`` matters more than it looks. Without it this returns one row per
    share, so a resource held by five hundred patients drags five hundred rows
    back to build a set of one.
    """
    if not resource_dbids:
        return set()
    return set(
        PatientResourceShare.objects.filter(
            resource__dbid__in=list(resource_dbids), revoked_at__isnull=True
        )
        .values_list("resource_id", flat=True)
        .distinct()
    )


def has_live_shares(resource: Any) -> bool:
    """True if a patient currently holds this resource.

    The server-side counterpart of the control above, so a direct request cannot
    withdraw something with nothing left to withdraw.
    """
    return PatientResourceShare.objects.filter(
        resource__dbid=resource.dbid, revoked_at__isnull=True
    ).exists()


def resources_with_withdrawn_shares(resource_dbids: list[Any]) -> set[Any]:
    """Which of these resources were actively pulled back from patients.

    Separate from ``resources_with_shares`` because the two answer different
    questions about the same rows: whether a patient ever received it, and
    whether it was taken back off them. An archived resource and a withdrawn one
    look identical in the library otherwise, though only one of them changed what
    patients already held.

    ``distinct()`` for the same reason as above: one row per resource, not one
    per withdrawal.
    """
    if not resource_dbids:
        return set()
    return set(
        PatientResourceShare.objects.filter(
            resource__dbid__in=list(resource_dbids), revoked_at__isnull=False
        )
        .values_list("resource_id", flat=True)
        .distinct()
    )


def share_resources(
    *,
    patient: Any,
    resource_dbids: list[Any],
    staff_dbid: Any,
    notes: dict[Any, str] | None = None,
) -> ShareResult:
    """Give a patient every one of these resources they do not already have.

    Three reads and one write, regardless of batch size. The already-shared set
    is computed up front rather than relying on ``bulk_create(ignore_conflicts)``:
    ignoring conflicts would make the created set unknowable, and the response has
    to distinguish "sent" from "already had".

    The unique constraint still backs this up, because the pre-check races with a
    second provider sending the same resource. The route catches
    ``IntegrityError`` and re-reports rather than 500ing.

    ``notes`` carries what the sender wrote for this patient, keyed by resource.
    A key that is present wins even when its value is empty -- the picker
    pre-fills the library default, so a box the sender cleared is a decision to
    send no note, not an omission. Only a resource absent from the mapping
    entirely falls back to ``default_note``.
    """
    requested = list(resource_dbids)[:MAX_SHARE_BATCH]
    if not requested:
        return ShareResult(created=[], already_shared=0, skipped_unavailable=0)

    available = {
        resource.dbid: resource
        for resource in PatientResource.objects.filter(
            dbid__in=requested, status=STATUS_ACTIVE
        )
    }
    unavailable = [dbid for dbid in requested if dbid not in available]

    existing = shared_resource_dbids(patient.dbid, list(available))
    to_create = [dbid for dbid in available if dbid not in existing]

    if not to_create:
        return ShareResult(
            created=[],
            already_shared=len(existing),
            skipped_unavailable=len(unavailable),
        )

    supplied = notes or {}
    now = datetime.now(timezone.utc)
    rows = [
        PatientResourceShare(
            patient_id=patient.dbid,
            resource_id=dbid,
            shared_by_id=staff_dbid,
            shared_at=now,
            # The snapshot is taken here, once. The URL is what the patient
            # opens from now on; the title is the fallback for a catalog row
            # that later goes missing.
            title_at_share=available[dbid].title or "",
            url_at_share=available[dbid].url or "",
            label_at_share=available[dbid].label or "",
            note=_note_for(dbid, supplied, available[dbid]),
        )
        for dbid in to_create
    ]
    created = PatientResourceShare.objects.bulk_create(rows)

    return ShareResult(
        created=list(created if created is not None else rows),
        already_shared=len(existing),
        skipped_unavailable=len(unavailable),
    )


def _note_for(resource_dbid: Any, supplied: dict[Any, str], resource: Any) -> str:
    """What to store as this share's patient-facing note.

    Membership decides, not truthiness: an empty string the sender left behind is
    a real answer, and only a resource the caller said nothing about inherits the
    library default.
    """
    if resource_dbid in supplied:
        return str(supplied[resource_dbid] or "").strip()
    return str(getattr(resource, "default_note", "") or "").strip()


def revoke_resource_shares(*, resource_dbid: Any, reason: str = "") -> int:
    """Withdraw a resource from every patient who has it. Returns the count."""
    now = datetime.now(timezone.utc)
    return PatientResourceShare.objects.filter(
        resource__dbid=resource_dbid,
        revoked_at__isnull=True,
    ).update(revoked_at=now, revoked_reason=reason or "")


def mark_viewed(patient_dbid: Any) -> int:
    """Stamp every unviewed live share for this patient. Returns the count.

    Takes a patient, never a share id. An endpoint that accepted a share id would
    be the one place in the portal surface where a patient could name a row, and
    naming a row is the whole shape of a cross-patient leak. "Opened the list" is
    also the honest semantic for what we actually observed.
    """
    return PatientResourceShare.objects.filter(
        patient__dbid=patient_dbid,
        first_viewed_at__isnull=True,
        revoked_at__isnull=True,
    ).update(first_viewed_at=datetime.now(timezone.utc))


def unviewed_count(patient_dbid: Any) -> int:
    """How many live resources this patient has not opened their list since."""
    return PatientResourceShare.objects.filter(
        patient__dbid=patient_dbid,
        first_viewed_at__isnull=True,
        revoked_at__isnull=True,
        resource__status=STATUS_ACTIVE,
    ).count()
