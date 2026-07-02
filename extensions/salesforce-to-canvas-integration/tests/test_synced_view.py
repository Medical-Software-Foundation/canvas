"""Tests for the Synced registry view and its endpoint.

Synced is the contact keyed registry, one row per Salesforce record linked to a
Canvas patient. The pure ``_synced_view`` builds a row from the newest event and
the most recent applied decision, and the ``/synced`` route assembles the linked
set, sorts by Last synced, collapses every event for a contact to one row, and
excludes unlinked contacts. See journal cnv-928/014 and 015.
"""

from __future__ import annotations

import json
from base64 import b64decode
from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import factory
import pytest

from salesforce_to_canvas_integration.handlers import status_api
from salesforce_to_canvas_integration.handlers.status_api import (
    SalesforceStatusAPI,
    _salesforce_record_url,
    _synced_view,
)
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.models.resolution_audit_entry import (
    ResolutionAuditEntry,
)
from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING

_PAYLOAD = {
    "Id": "00QSYN001",
    "FirstName": "Ada",
    "LastName": "Lovelace",
    "Phone": "+15551112222",
    "Birthdate": "1990-04-15",
    "Gender": "female",
}


class EventFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured event carrying a full Salesforce payload, defaulting to a create."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QSYN001"
    source_object = "Contact"
    action = "create"
    first_name = "Ada"
    last_name = "Lovelace"
    email = ""
    phone = "+15551112222"
    raw_payload = factory.LazyAttribute(lambda o: dict(_PAYLOAD, Id=o.external_id))
    content_hash = factory.Sequence(lambda n: f"syn-{n}")
    status = "accepted"


@pytest.fixture(autouse=True)
def _stub_token_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the token cache so the route runs outside a real plugin context.

    The synced route reads the stored Salesforce instance url for the record
    link through ``TokenStore(get_cache())``, and ``get_cache`` demands a plugin
    runtime that the unit test harness does not provide. With no tokens the
    instance url is empty and the Salesforce link is omitted, which the route
    tests do not assert on.
    """

    class _NoTokens:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def load(self) -> None:
            return None

    monkeypatch.setattr(status_api, "get_cache", lambda: None)
    monkeypatch.setattr(status_api, "TokenStore", _NoTokens)


def _make_api() -> SalesforceStatusAPI:
    handler = SalesforceStatusAPI.__new__(SalesforceStatusAPI)
    handler.event = MagicMock()
    handler.secrets = {}
    handler.environment = {}
    handler._handler = None
    handler._path_pattern = None
    handler.request = MagicMock()
    handler.request.query_params = {}
    return handler


def _json_body(effect: Any) -> dict[str, Any]:
    payload = json.loads(effect.payload)
    return json.loads(b64decode(payload["body"]).decode())


def _link_patient(external_id: str) -> Any:
    from canvas_sdk.test_utils.factories import PatientFactory
    from canvas_sdk.v1.data.patient import PatientExternalIdentifier

    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value=external_id,
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )
    return patient


# ---------------------------------------------------------------------------
# pure view and link helpers
# ---------------------------------------------------------------------------


def test_synced_view_builds_links_demographics_and_last_synced() -> None:
    """The view maps the newest event and fills the links and Last synced clock."""
    event = EventFactory.create()
    last_applied = {
        "created_at": "2026-05-30T10:00:00+00:00",
        "staff_name": "Grace Hopper",
    }

    row = _synced_view(
        "00QSYN001",
        "abc123def",
        event,
        last_applied,
        DEFAULT_FIELD_MAPPING,
        "https://org.lightning.force.com",
    )

    assert row["first_name"] == "Ada"
    assert row["last_name"] == "Lovelace"
    assert row["date_of_birth"] == "1990-04-15"
    assert row["sex_at_birth"] == "female"
    assert row["phone"] == "+15551112222"
    assert row["patient_id"] == "abc123def"
    assert (
        row["salesforce_url"]
        == "https://org.lightning.force.com/lightning/r/Contact/00QSYN001/view"
    )
    assert row["last_synced_at"] == "2026-05-30T10:00:00+00:00"
    assert row["last_acted_by"] == "Grace Hopper"


def test_synced_view_without_applied_decision_has_no_last_synced() -> None:
    """A contact with no applied decision leaves Last synced and actor empty."""
    event = EventFactory.create()

    row = _synced_view(
        "00QSYN001", "abc", event, None, DEFAULT_FIELD_MAPPING, "https://org"
    )

    assert row["last_synced_at"] is None
    assert row["last_acted_by"] == ""


def test_salesforce_record_url_degrades_without_instance_or_id() -> None:
    """The Salesforce link is empty with no instance url or no external id."""
    assert _salesforce_record_url("", "Contact", "00Q") == ""
    assert _salesforce_record_url("https://org", "Lead", "") == ""
    # An empty source object falls back to Contact rather than a broken path.
    assert (
        _salesforce_record_url("https://org", "", "00Q")
        == "https://org/lightning/r/Contact/00Q/view"
    )


# ---------------------------------------------------------------------------
# /synced endpoint
# ---------------------------------------------------------------------------


def test_synced_returns_only_linked_contacts() -> None:
    """A contact appears in Synced only when a Canvas patient carries its link."""
    linked = EventFactory.create(external_id="00QLINK")
    _link_patient("00QLINK")
    ResolutionAuditEntry.objects.create(
        external_id="00QLINK",
        event_id=linked.pk,
        action="create",
        action_taken="created",
        staff_name="Grace Hopper",
    )

    unlinked = EventFactory.create(external_id="00QUNLINK")
    ResolutionAuditEntry.objects.create(
        external_id="00QUNLINK",
        event_id=unlinked.pk,
        action="create",
        action_taken="created",
    )

    body = _json_body(_make_api().synced()[0])

    assert [r["external_id"] for r in body["synced"]] == ["00QLINK"]
    assert body["synced"][0]["patient_id"]


def test_synced_sorts_by_last_synced_newest_first() -> None:
    """Synced sorts by the most recent applied decision, newest first."""
    from datetime import UTC, datetime

    old_event = EventFactory.create(external_id="00QOLD")
    _link_patient("00QOLD")
    old_decision = ResolutionAuditEntry.objects.create(
        external_id="00QOLD",
        event_id=old_event.pk,
        action="create",
        action_taken="created",
    )
    ResolutionAuditEntry.objects.filter(dbid=old_decision.dbid).update(
        created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    new_event = EventFactory.create(external_id="00QNEW")
    _link_patient("00QNEW")
    new_decision = ResolutionAuditEntry.objects.create(
        external_id="00QNEW",
        event_id=new_event.pk,
        action="modify",
        action_taken="modify_applied",
    )
    ResolutionAuditEntry.objects.filter(dbid=new_decision.dbid).update(
        created_at=datetime(2026, 2, 1, tzinfo=UTC)
    )

    body = _json_body(_make_api().synced()[0])

    assert [r["external_id"] for r in body["synced"]] == ["00QNEW", "00QOLD"]


def test_synced_collapses_create_and_modifies_to_one_row() -> None:
    """Many events for one contact collapse to one row, demographics from the chart.

    The demographic columns read the linked Canvas patient, the source of truth,
    so the row shows the chart name even when a later event carried a different
    one. The collapse to a single row is unchanged. See journal cnv-928/026.
    """
    from datetime import UTC, datetime

    create = EventFactory.create(
        external_id="00QMANY", action="create", content_hash="many-c"
    )
    modify = EventFactory.create(
        external_id="00QMANY",
        action="modify",
        content_hash="many-m",
        raw_payload=dict(_PAYLOAD, Id="00QMANY", FirstName="Adabella"),
    )
    IncomingPatientRecord.objects.filter(dbid=create.dbid).update(
        received_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    IncomingPatientRecord.objects.filter(dbid=modify.dbid).update(
        received_at=datetime(2026, 2, 1, tzinfo=UTC)
    )
    patient = _link_patient("00QMANY")
    ResolutionAuditEntry.objects.create(
        external_id="00QMANY",
        event_id=modify.pk,
        action="modify",
        action_taken="modify_applied",
    )

    body = _json_body(_make_api().synced()[0])

    assert len(body["synced"]) == 1
    assert body["synced"][0]["first_name"] == patient.first_name


def test_synced_row_shows_chart_demographics_with_no_event() -> None:
    """A linked patient with no captured event still renders its chart demographics.

    This is the blank row regression. The Salesforce link lives on the Canvas
    patient and survives a cleared event log, so a contact whose events are gone
    used to render an empty row. The demographics now come from the chart, so the
    row stays populated regardless of the event log. See journal cnv-928/026.
    """
    from canvas_sdk.test_utils.factories import PatientFactory
    from canvas_sdk.v1.data.patient import PatientExternalIdentifier

    patient = PatientFactory.create(first_name="Nadia", last_name="Comaneci")
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value="00QNOEVENT",
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )

    body = _json_body(_make_api().synced()[0])

    assert len(body["synced"]) == 1
    row = body["synced"][0]
    assert row["external_id"] == "00QNOEVENT"
    assert row["first_name"] == "Nadia"
    assert row["last_name"] == "Comaneci"
    assert row["last_synced_at"] is None
