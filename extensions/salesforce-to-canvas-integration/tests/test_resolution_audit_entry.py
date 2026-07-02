"""Tests for the ResolutionAuditEntry decision log model.

These hit the Django ORM, so they run where canvas_sdk is importable. The
pytest-canvas plugin pulled in by canvas[test-utils] provides an autouse
transaction(db) fixture, so no django_db marker is needed. The model is append
only, so the tests check that entries persist with their fields intact and that
several entries can coexist for one external id, which is the whole point of the
decision log over the newest per record collapse. See journal cnv-909/089.
"""

from __future__ import annotations

from datetime import UTC, datetime

import factory

from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)


class ResolutionAuditEntryFactory(
    factory.django.DjangoModelFactory[ResolutionAuditEntry]
):
    """A decision log entry pinned to a known external id for the tests."""

    class Meta:
        model = ResolutionAuditEntry

    external_id = "003SFAUDIT"
    event_id = factory.Sequence(lambda n: n + 1)
    action = "create"
    action_taken = "created"
    staff_key = "deadbeefdeadbeefdeadbeefdeadbeef"
    staff_name = "Ada Lovelace"


def _backdate(entry: ResolutionAuditEntry, when: datetime) -> None:
    """Set created_at directly. auto_now_add ignores values on create, but a
    queryset update writes the column without firing auto_now_add, so this makes
    the timeline ordering deterministic.
    """
    ResolutionAuditEntry.objects.filter(dbid=entry.dbid).update(created_at=when)


def test_entry_persists_with_its_fields_intact() -> None:
    """A written entry reads back with every field as supplied."""
    entry = ResolutionAuditEntryFactory.create(
        action="modify",
        action_taken="modify_applied",
        result_patient_id="patient-123",
        note="reopened after a skip",
    )

    fetched = ResolutionAuditEntry.objects.get(dbid=entry.dbid)
    assert fetched.external_id == "003SFAUDIT"
    assert fetched.action == "modify"
    assert fetched.action_taken == "modify_applied"
    assert fetched.staff_key == "deadbeefdeadbeefdeadbeefdeadbeef"
    assert fetched.staff_name == "Ada Lovelace"
    assert fetched.result_patient_id == "patient-123"
    assert fetched.note == "reopened after a skip"
    assert fetched.created_at is not None


def test_optional_fields_default_to_empty() -> None:
    """note, result_patient_id, and edits are optional and default empty."""
    entry = ResolutionAuditEntryFactory.create()

    fetched = ResolutionAuditEntry.objects.get(dbid=entry.dbid)
    assert fetched.note == ""
    assert fetched.result_patient_id == ""
    assert fetched.edits == {}


def test_edits_round_trips_as_json() -> None:
    """edits is a JSONField, so a field level before and after dict survives."""
    edits = {"email": {"before": "old@example.com", "after": "new@example.com"}}
    entry = ResolutionAuditEntryFactory.create(edits=edits)

    fetched = ResolutionAuditEntry.objects.get(dbid=entry.dbid)
    assert fetched.edits == edits


def test_many_entries_coexist_for_one_external_id_in_order() -> None:
    """The log keeps every decision for a record, not just the newest.

    This is the property the decision log adds over the newest per record
    collapse. A create then a skip then a reopen all stay as distinct rows, and
    the created_at ordering reconstructs the timeline.
    """
    created = ResolutionAuditEntryFactory.create(
        external_id="003TIMELINE", action="create", action_taken="created"
    )
    skipped = ResolutionAuditEntryFactory.create(
        external_id="003TIMELINE", action="modify", action_taken="skipped"
    )
    applied = ResolutionAuditEntryFactory.create(
        external_id="003TIMELINE", action="modify", action_taken="modify_applied"
    )
    _backdate(created, datetime(2026, 1, 1, tzinfo=UTC))
    _backdate(skipped, datetime(2026, 1, 2, tzinfo=UTC))
    _backdate(applied, datetime(2026, 1, 3, tzinfo=UTC))

    timeline = list(
        ResolutionAuditEntry.objects.filter(external_id="003TIMELINE").order_by(
            "created_at"
        )
    )

    assert [e.action_taken for e in timeline] == [
        "created",
        "skipped",
        "modify_applied",
    ]
