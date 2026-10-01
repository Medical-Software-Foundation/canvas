"""Tests for the Salesforce → Canvas field mapper."""

from __future__ import annotations

import pytest

from salesforce_to_canvas_integration.services.config import DEFAULT_FIELD_MAPPING
from salesforce_to_canvas_integration.services.field_mapping import (
    MappedPatient,
    MappingError,
    build_promote_prefill,
    map_record,
)


def test_default_mapping_extracts_core_fields() -> None:
    record = {
        "FirstName": "Jane",
        "LastName": "Doe",
        "Birthdate": "1985-04-12",
        "Email": "jane@example.com",
        "Phone": "+15551234567",
        "MailingStreet": "10 Main St\nApt 4B",
        "MailingCity": "Springfield",
        "MailingState": "IL",
        "MailingPostalCode": "62704",
        "MailingCountry": "US",
        "Gender": "Female",
        "Preferred_Language__c": "Spanish",
        "Referral_Source__c": "Web",
    }

    mapped = map_record(record, DEFAULT_FIELD_MAPPING)

    assert mapped.canvas_fields == {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "1985-04-12",
        "email": "jane@example.com",
        "phone": "+15551234567",
        "address_line_1": "10 Main St",
        "address_line_2": "Apt 4B",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62704",
        "country": "US",
        "sex_at_birth": "female",
    }
    assert mapped.metadata == {
        "preferred_language": "Spanish",
        "referral_source": "Web",
    }


def test_empty_or_missing_values_are_skipped() -> None:
    record = {"FirstName": "", "LastName": "Doe", "Email": None}
    mapped = map_record(record, DEFAULT_FIELD_MAPPING)
    assert "first_name" not in mapped.canvas_fields
    assert mapped.canvas_fields["last_name"] == "Doe"
    assert mapped.has_required(required=("last_name",))


def test_custom_metadata_target_routes_to_metadata_dict() -> None:
    mapping = {"Custom_Insurance_Name__c": {"target": "metadata.insurance_provider"}}
    mapped = map_record({"Custom_Insurance_Name__c": "Aetna"}, mapping)
    assert mapped.canvas_fields == {}
    assert mapped.metadata == {"insurance_provider": "Aetna"}


def test_telecom_target_routes_to_telecom_dict() -> None:
    mapping = {"MobilePhone": {"target": "telecom.mobile"}}
    mapped = map_record({"MobilePhone": "+15559998888"}, mapping)
    assert mapped.telecom == {"mobile": "+15559998888"}
    assert mapped.canvas_fields == {}


def test_gender_normalisation_drops_unrecognised_values() -> None:
    mapped = map_record({"Gender": "spaceship"}, DEFAULT_FIELD_MAPPING)
    assert "sex_at_birth" not in mapped.canvas_fields


def test_missing_target_raises_mapping_error() -> None:
    with pytest.raises(MappingError):
        map_record({"FirstName": "Jane"}, {"FirstName": {}})


# ---------------------------------------------------------------------------
# build_promote_prefill, story five gap fill plus server side diff
# ---------------------------------------------------------------------------


def test_promote_prefill_with_no_prior_returns_incoming_untouched() -> None:
    incoming = map_record(
        {"FirstName": "Ada", "LastName": "King"}, DEFAULT_FIELD_MAPPING
    )
    prefill = build_promote_prefill(incoming, None)
    assert prefill.mapped is incoming
    assert prefill.gap_filled == ()
    assert prefill.changed == ()


def test_promote_prefill_fills_only_blanks_and_incoming_wins() -> None:
    # The modify carries a new email but left the address and phone blank, the
    # prior create carried them. Gap fill offers the prior values for the blanks
    # and never touches the field the modify changed.
    incoming = map_record(
        {"LastName": "King", "Email": "ada.king@new.example.com"},
        DEFAULT_FIELD_MAPPING,
    )
    prior = map_record(
        {
            "LastName": "King",
            "Email": "ada@old.example.com",
            "Phone": "+15551234567",
            "MailingCity": "Springfield",
        },
        DEFAULT_FIELD_MAPPING,
    )
    prefill = build_promote_prefill(incoming, prior)

    # Incoming wins on the field it populated.
    assert prefill.mapped.canvas_fields["email"] == "ada.king@new.example.com"
    # Blanks are filled from the prior event.
    assert prefill.mapped.canvas_fields["phone"] == "+15551234567"
    assert prefill.mapped.canvas_fields["city"] == "Springfield"
    # gap_filled names only the fields sourced from the prior event.
    assert prefill.gap_filled == ("city", "phone")
    # email differs between incoming and prior, so it is the server side diff.
    assert prefill.changed == ("email",)


def test_promote_prefill_merges_telecom_and_metadata() -> None:
    incoming = MappedPatient(
        canvas_fields={"last_name": "King"},
        metadata={"mrn": "MRN-NEW"},
        telecom={},
    )
    prior = MappedPatient(
        canvas_fields={"last_name": "King"},
        metadata={"mrn": "MRN-OLD", "preferred_language": "Spanish"},
        telecom={"mobile": "+15550001111"},
    )
    prefill = build_promote_prefill(incoming, prior)
    # Incoming metadata wins, prior fills the gaps.
    assert prefill.mapped.metadata == {
        "mrn": "MRN-NEW",
        "preferred_language": "Spanish",
    }
    assert prefill.mapped.telecom == {"mobile": "+15550001111"}
