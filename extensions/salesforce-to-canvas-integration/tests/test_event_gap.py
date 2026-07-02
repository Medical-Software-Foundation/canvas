"""Tests for the story six gap banner computation.

``_compute_event_gap`` is pure, it takes the record's events plus the decision
log derived inputs and counts the unresolved events between the resolved event
and its anchor. It is exercised with real rows so the pk and received_at match
production, but it runs no Postgres only query, the same SQLite friendly pattern
as ``_bucket_records``. See journal cnv-909/088 The Gap Banner and 092 story six.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import factory

from salesforce_to_canvas_integration.handlers.status_api import _compute_event_gap
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)


class RowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured event for one record, defaulting to a pending modify."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QGAP"
    source_object = "Contact"
    action = "modify"
    last_name = "Lovelace"
    raw_payload = factory.LazyAttribute(lambda o: {"Id": o.external_id})
    content_hash = factory.Sequence(lambda n: f"gap-hash-{n}")
    status = "new"


_BASE = datetime(2026, 5, 1, tzinfo=UTC)


def _row(action: str, status: str, *, minutes: int) -> IncomingPatientRecord:
    """Create a row at a deterministic received_at offset from a base time.

    received_at is auto_now_add, so it is set after create the same way the
    bucketing tests pin their timestamps.
    """
    row = RowFactory.create(action=action, status=status)
    IncomingPatientRecord.objects.filter(dbid=row.dbid).update(
        received_at=_BASE + timedelta(minutes=minutes)
    )
    row.refresh_from_db()
    return row


def test_gap_no_anchor_counts_skipped_creation() -> None:
    """A skipped create before a modify, no anchor, reads as one skipped event."""
    create = _row("create", "dismissed", minutes=0)
    modify = _row("modify", "new", minutes=10)

    gap = _compute_event_gap(
        modify, [create, modify], set(), {create.pk: "Grace Hopper"}
    )

    assert gap["count"] == 1
    assert gap["has_anchor"] is False
    assert gap["older_than_last_applied"] is False
    assert [e["action"] for e in gap["events"]] == ["create"]
    assert gap["events"][0]["status"] == "dismissed"
    assert gap["events"][0]["who"] == "Grace Hopper"


def test_gap_zero_when_nothing_between_anchor_and_current() -> None:
    """An applied modify is the anchor, the next modify has an empty gap."""
    applied = _row("modify", "accepted", minutes=0)
    current = _row("modify", "new", minutes=10)

    gap = _compute_event_gap(current, [applied, current], {applied.pk}, {})

    assert gap["count"] == 0
    assert gap["has_anchor"] is True
    assert gap["events"] == []


def test_gap_counts_skipped_modify_since_last_applied() -> None:
    """A skipped modify between the anchor and current reads as one modification."""
    applied = _row("modify", "accepted", minutes=0)
    skipped = _row("modify", "dismissed", minutes=10)
    current = _row("modify", "new", minutes=20)

    gap = _compute_event_gap(
        current, [applied, skipped, current], {applied.pk}, {skipped.pk: "Ada Byron"}
    )

    assert gap["count"] == 1
    assert gap["has_anchor"] is True
    assert gap["events"][0]["event_id"] == skipped.pk
    assert gap["events"][0]["who"] == "Ada Byron"


def test_gap_flags_event_older_than_last_applied() -> None:
    """A pending event older than a newer applied change trips the warn flag."""
    older = _row("modify", "new", minutes=0)
    applied = _row("modify", "accepted", minutes=10)

    gap = _compute_event_gap(older, [older, applied], {applied.pk}, {})

    assert gap["older_than_last_applied"] is True
    # The applied change is newer than current so it is not a gap event, and
    # nothing sits before current, so there is nothing to count.
    assert gap["count"] == 0
    assert gap["has_anchor"] is False


def test_gap_counts_both_skipped_and_pending_oldest_first() -> None:
    """The gap counts skipped and still pending events, ordered oldest first."""
    create = _row("create", "dismissed", minutes=0)
    pending_modify = _row("modify", "new", minutes=10)
    current = _row("modify", "new", minutes=20)

    gap = _compute_event_gap(
        current,
        [create, pending_modify, current],
        set(),
        {create.pk: "Grace Hopper"},
    )

    assert gap["count"] == 2
    assert [e["event_id"] for e in gap["events"]] == [create.pk, pending_modify.pk]
    by_id = {e["event_id"]: e for e in gap["events"]}
    assert by_id[create.pk]["who"] == "Grace Hopper"
    assert by_id[pending_modify.pk]["who"] == ""
    assert by_id[pending_modify.pk]["status"] == "new"


def test_gap_ignores_accepted_event_that_did_not_change_canvas() -> None:
    """An accepted but not Canvas changing event is neither anchor nor gap.

    A create closed as superseded is accepted, so it is not unresolved, and it
    is absent from the Canvas changing set, so it never anchors the gap.
    """
    superseded = _row("create", "accepted", minutes=0)
    current = _row("modify", "new", minutes=10)

    gap = _compute_event_gap(current, [superseded, current], set(), {})

    assert gap["count"] == 0
    assert gap["has_anchor"] is False
    assert gap["older_than_last_applied"] is False


def test_gap_excludes_other_records_via_supplied_event_list() -> None:
    """The helper only sees the events handed to it, never another record's."""
    skipped = _row("create", "dismissed", minutes=0)
    current = _row("modify", "new", minutes=10)

    # Only current is in the list, so the earlier skipped event is invisible.
    gap = _compute_event_gap(current, [current], set(), {skipped.pk: "Grace Hopper"})

    assert gap["count"] == 0
    assert gap["events"] == []
