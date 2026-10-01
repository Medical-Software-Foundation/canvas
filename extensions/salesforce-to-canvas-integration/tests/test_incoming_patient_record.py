"""Tests for the IncomingPatientRecord custom data model.

These hit the Django ORM, so they run where canvas_sdk is importable. The
pytest-canvas plugin pulled in by canvas[test-utils] provides an autouse
transaction(db) fixture, so no django_db marker is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import factory

from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.proxy import PatientProxy, StaffProxy

from canvas_sdk.test_utils.factories import PatientFactory, StaffFactory


class PatientProxyFactory(PatientFactory, factory.django.DjangoModelFactory[PatientProxy]):
    """PatientProxy factory, inheriting default field values from PatientFactory."""

    class Meta:
        model = PatientProxy


class StaffProxyFactory(StaffFactory, factory.django.DjangoModelFactory[StaffProxy]):
    """StaffProxy factory, inheriting default field values from StaffFactory."""

    class Meta:
        model = StaffProxy


class IncomingPatientRecordFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """An inbound capture row, with the decision fields left empty by default."""

    class Meta:
        model = IncomingPatientRecord

    external_id = factory.Sequence(lambda n: f"003SF{n:09d}")
    source_object = "Contact"
    action = "create"
    first_name = "Jane"
    last_name = "Doe"
    email = "jane@example.com"
    phone = "+15551234567"
    raw_payload = factory.LazyAttribute(
        lambda o: {"Id": o.external_id, "FirstName": o.first_name, "LastName": o.last_name}
    )
    content_hash = factory.Sequence(lambda n: f"hash-{n}")
    status = "new"


def _backdate(row: IncomingPatientRecord, when: datetime) -> None:
    """Set received_at directly. auto_now_add ignores values on create, but a
    queryset update writes the column without firing auto_now_add, so this makes
    the newest-row ordering deterministic.
    """
    IncomingPatientRecord.objects.filter(dbid=row.dbid).update(received_at=when)


def test_inbound_row_persists_with_empty_decision_fields() -> None:
    """An inbound capture lands with status new and no patient, staff, or action time."""
    row = IncomingPatientRecordFactory.create()

    assert row.dbid is not None
    assert row.status == "new"
    assert row.received_at is not None
    assert row.canvas_patient_id is None
    assert row.actioned_by_id is None
    assert row.actioned_at is None


def test_raw_payload_round_trips_as_json() -> None:
    """raw_payload is a JSONField, so a nested dict survives a write and read."""
    payload = {"Id": "003JSON", "FirstName": "Jane", "Nested": {"a": 1, "b": [2, 3]}}
    row = IncomingPatientRecordFactory.create(raw_payload=payload)

    fetched = IncomingPatientRecord.objects.get(dbid=row.dbid)
    assert fetched.raw_payload == payload


def test_newest_row_lookup_is_scoped_to_external_id_and_action() -> None:
    """The webhook dedup query finds the newest row for one external_id and action.

    Rows for a different external_id or a different action must not be returned,
    which is what the composite index on external_id, action, and received_at
    descending backs.
    """
    older = IncomingPatientRecordFactory.create(
        external_id="003NEWEST", action="create", content_hash="older"
    )
    newer = IncomingPatientRecordFactory.create(
        external_id="003NEWEST", action="create", content_hash="newer"
    )
    _backdate(older, datetime(2026, 1, 1, tzinfo=UTC))
    _backdate(newer, datetime(2026, 2, 1, tzinfo=UTC))

    # Noise that must be excluded by the filter.
    IncomingPatientRecordFactory.create(
        external_id="003OTHER", action="create", content_hash="other-id"
    )
    IncomingPatientRecordFactory.create(
        external_id="003NEWEST", action="update", content_hash="other-action"
    )

    newest = (
        IncomingPatientRecord.objects.filter(external_id="003NEWEST", action="create")
        .order_by("-received_at")
        .first()
    )

    assert newest is not None
    assert newest.dbid == newer.dbid
    assert newest.content_hash == "newer"


def test_create_row_links_canvas_patient_resolvable_by_external_id() -> None:
    """A converted create row carries the patient linkage, resolvable by external_id.

    This is the reverse lookup an update or delete uses, external_id plus
    action create, then read that row's canvas_patient.
    """
    patient = PatientProxyFactory.create()
    staff = StaffProxyFactory.create()
    IncomingPatientRecordFactory.create(
        external_id="003LINK",
        action="create",
        status="accepted",
        canvas_patient=patient,
        actioned_by=staff,
        actioned_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )

    create_row = (
        IncomingPatientRecord.objects.filter(external_id="003LINK", action="create")
        .select_related("canvas_patient", "actioned_by")
        .first()
    )

    assert create_row is not None
    assert create_row.status == "accepted"
    assert create_row.canvas_patient is not None
    assert create_row.canvas_patient.dbid == patient.dbid
    assert create_row.actioned_by.dbid == staff.dbid
