"""Tests for the enriched admin status record view.

These exercise ``_record_view`` against the ORM, so they run where canvas_sdk is
importable. The autouse transaction(db) fixture from pytest-canvas covers the DB.
"""

from __future__ import annotations

import factory

from salesforce_to_canvas_integration.handlers.status_api import _record_view
from salesforce_to_canvas_integration.models.incoming_patient_record import (
    IncomingPatientRecord,
)
from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING

_LEAD_PAYLOAD = {
    "Id": "00QLEAD001",
    "FirstName": "Ada",
    "LastName": "Lovelace",
    "Email": "ada@example.com",
    "Phone": "+15551112222",
    "MobilePhone": "+15553334444",
    "Birthdate": "1990-04-15",
    "Gender": "female",
    "MailingStreet": "1 Analytical Way",
    "MailingCity": "London",
    "MailingState": "CA",
    "MailingPostalCode": "90210",
    "MailingCountry": "US",
    "Preferred_Language__c": "English",
}


class LeadRecordFactory(factory.django.DjangoModelFactory[IncomingPatientRecord]):
    """A captured Lead row carrying a full Salesforce payload."""

    class Meta:
        model = IncomingPatientRecord

    external_id = "00QLEAD001"
    source_object = "Lead"
    action = "create"
    first_name = "Ada"
    last_name = "Lovelace"
    email = "ada@example.com"
    phone = "+15551112222"
    raw_payload = _LEAD_PAYLOAD
    content_hash = "hash-lead-001"
    status = "new"


def test_record_view_exposes_mapped_demographics_beyond_typed_columns() -> None:
    """The view surfaces DOB, sex, address, mobile, and metadata from the payload."""
    row = LeadRecordFactory.create()
    view = _record_view(row, DEFAULT_FIELD_MAPPING)

    assert view["mapped"]["date_of_birth"] == "1990-04-15"
    assert view["mapped"]["sex_at_birth"] == "female"
    assert view["mapped"]["address_line_1"] == "1 Analytical Way"
    assert view["mapped"]["city"] == "London"
    assert view["mapped"]["state"] == "CA"
    assert view["mapped"]["postal_code"] == "90210"
    assert view["telecom"]["mobile"] == "+15553334444"
    assert view["metadata"]["preferred_language"] == "English"


def test_record_view_includes_full_raw_payload() -> None:
    """The complete Salesforce payload rides along for the raw expander."""
    row = LeadRecordFactory.create()
    view = _record_view(row, DEFAULT_FIELD_MAPPING)

    assert view["raw_payload"]["Id"] == "00QLEAD001"
    assert view["raw_payload"]["MobilePhone"] == "+15553334444"


def test_record_view_carries_the_event_id() -> None:
    """The view exposes the event primary key so the per event queue can target it.

    Story four keys the payload viewer and the resolution routes on the event
    id, since one Salesforce record can now show more than one live event at
    once. See journal cnv-909/092 story four.
    """
    row = LeadRecordFactory.create()
    view = _record_view(row, DEFAULT_FIELD_MAPPING)

    assert view["event_id"] == row.pk


def test_record_view_degrades_to_typed_columns_on_empty_payload() -> None:
    """An empty payload yields no mapped fields but keeps the typed columns."""
    row = LeadRecordFactory.create(raw_payload={})
    view = _record_view(row, DEFAULT_FIELD_MAPPING)

    assert view["mapped"] == {}
    assert view["telecom"] == {}
    assert view["first_name"] == "Ada"
    assert view["last_name"] == "Lovelace"
    assert view["raw_payload"] == {}


def test_record_view_marks_create_row_as_not_linked_check() -> None:
    """Create rows do not run the linked patient lookup, the flag stays False."""
    row = LeadRecordFactory.create()
    view = _record_view(row, DEFAULT_FIELD_MAPPING)
    assert view["linked"] is False


def test_record_view_marks_modify_row_unlinked_when_no_canvas_patient() -> None:
    """Modify rows without a matching Salesforce external identifier are unlinked."""
    row = LeadRecordFactory.create(action="modify")
    view = _record_view(row, DEFAULT_FIELD_MAPPING)
    assert view["linked"] is False


def test_record_view_marks_modify_row_linked_when_external_identifier_exists() -> None:
    """A modify row with a matching SF external identifier on a Canvas patient is linked."""
    from datetime import date, timedelta

    from canvas_sdk.test_utils.factories import PatientFactory
    from canvas_sdk.v1.data.patient import PatientExternalIdentifier

    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value="00QLEAD001",
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )

    row = LeadRecordFactory.create(action="modify")
    view = _record_view(row, DEFAULT_FIELD_MAPPING)
    assert view["linked"] is True


def test_record_view_marks_delete_row_unlinked_when_no_canvas_patient() -> None:
    """Delete rows without a matching Salesforce external identifier are unlinked."""
    row = LeadRecordFactory.create(action="delete")
    view = _record_view(row, DEFAULT_FIELD_MAPPING)
    assert view["linked"] is False


def test_record_view_marks_delete_row_linked_when_external_identifier_exists() -> None:
    """A delete row pointing to a linked Canvas patient shows linked True."""
    from datetime import date, timedelta

    from canvas_sdk.test_utils.factories import PatientFactory
    from canvas_sdk.v1.data.patient import PatientExternalIdentifier

    patient = PatientFactory.create()
    today = date.today()
    PatientExternalIdentifier.objects.create(
        patient=patient,
        use="official",
        identifier_type="external",
        system="salesforce",
        value="00QLEAD001",
        issued_date=today,
        expiration_date=today + timedelta(days=365),
    )

    row = LeadRecordFactory.create(action="delete")
    view = _record_view(row, DEFAULT_FIELD_MAPPING)
    assert view["linked"] is True
