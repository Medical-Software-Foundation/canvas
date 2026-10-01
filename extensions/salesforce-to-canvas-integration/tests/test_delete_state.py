"""Tests for how a delete row behaves in the collapsed needs action bucket.

Records collapses each contact to one row, the newest pending event across every
action, because a one directional sync means the latest Salesforce state is the
truth. A delete is the live row only when a Canvas patient is linked, the one
case where a delete can act. A delete that is the newest event with no linked
patient has nothing to delete, so it drops off the Records surface entirely and
lives on only in the Activity ledger. The older delete state machine, the
no_patient_with_history and no_patient_no_history states, left with the collapse.
See journal cnv-938/022.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import factory

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from salesforce_to_canvas_integration.handlers.status_api import _bucket_records
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)


class RowFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured row, defaulting to a pending create."""

    class Meta:
        model = IncomingPatientRecord

    external_id = factory.Sequence(lambda n: f"00Q{n:08d}")
    source_object = "Contact"
    action = "create"
    first_name = "Ada"
    last_name = "Lovelace"
    email = "ada@example.com"
    phone = "+15551112222"
    raw_payload = factory.LazyAttribute(lambda o: {"Id": o.external_id})
    content_hash = factory.Sequence(lambda n: f"dstate-{n}")
    status = "new"


def _seed_linked_patient(external_id: str) -> Any:
    """Link a Canvas patient to a Salesforce id through the external identifier."""
    from datetime import date

    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system=SALESFORCE_IDENTIFIER_SYSTEM,
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


def _set_received(row: IncomingPatientRecord, when: datetime) -> None:
    """Stamp received_at explicitly so arrival order is deterministic."""
    IncomingPatientRecord.objects.filter(dbid=row.dbid).update(received_at=when)
    row.refresh_from_db()


def test_delete_with_linked_patient_is_the_live_row() -> None:
    """A delete whose Salesforce id maps to a Canvas patient is an actionable row."""
    _seed_linked_patient("00QLINK")
    delete = RowFactory.create(external_id="00QLINK", action="delete", status="new")

    pending, _skipped = _bucket_records([delete], DEFAULT_FIELD_MAPPING)

    assert len(pending) == 1
    view = pending[0]
    assert view["action"] == "delete"
    assert view["actionable"] is True


def test_no_patient_delete_drops_off_records() -> None:
    """A newest delete with no linked patient has nothing to delete, so it drops."""
    delete = RowFactory.create(
        external_id="00QNONE", action="delete", status="new", content_hash="nh1"
    )

    pending, _skipped = _bucket_records([delete], DEFAULT_FIELD_MAPPING)

    assert pending == []


def test_no_patient_delete_drops_even_with_an_older_pending_modify() -> None:
    """The newest event wins. A delete supersedes an older modify and, with no
    linked patient, the contact leaves Records entirely. The modify is history in
    the Activity ledger, not a separate live row."""
    modify = RowFactory.create(
        external_id="00QMOD", action="modify", status="new", content_hash="cm1"
    )
    delete = RowFactory.create(
        external_id="00QMOD", action="delete", status="new", content_hash="cm2"
    )
    _set_received(modify, datetime(2026, 1, 10, tzinfo=UTC))
    _set_received(delete, datetime(2026, 2, 1, tzinfo=UTC))

    pending, _skipped = _bucket_records([modify, delete], DEFAULT_FIELD_MAPPING)

    assert pending == []


def test_older_delete_with_a_newer_pending_sync_is_superseded() -> None:
    """When a create or modify arrives after a delete, the sync is the live row and
    the older delete is suppressed, it rides in the overridden history."""
    delete = RowFactory.create(
        external_id="00QSEQ", action="delete", status="new", content_hash="s1"
    )
    modify = RowFactory.create(
        external_id="00QSEQ", action="modify", status="new", content_hash="s2"
    )
    _set_received(delete, datetime(2026, 1, 10, tzinfo=UTC))
    _set_received(modify, datetime(2026, 2, 1, tzinfo=UTC))

    pending, _skipped = _bucket_records([delete, modify], DEFAULT_FIELD_MAPPING)

    assert len(pending) == 1
    assert pending[0]["event_id"] == modify.pk
    assert pending[0]["action"] in ("create", "modify")


def test_no_row_carries_a_delete_state_key() -> None:
    """The derived delete state machine is gone, no surfaced row carries its keys."""
    _seed_linked_patient("00QLINK2")
    delete = RowFactory.create(external_id="00QLINK2", action="delete", status="new")
    create = RowFactory.create(external_id="00QCR", action="create", status="new")

    pending, _skipped = _bucket_records([delete, create], DEFAULT_FIELD_MAPPING)

    for view in pending:
        assert "delete_state" not in view
        assert "delete_blocked_by" not in view
