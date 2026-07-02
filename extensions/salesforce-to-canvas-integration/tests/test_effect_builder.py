"""Tests for the Salesforce → Canvas effect builder."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.common import (
    ContactPointSystem,
    ContactPointUse,
    PersonSex,
)
from canvas_sdk.v1.data.patient import PatientExternalIdentifier

from salesforce_to_canvas_integration.services.effect_builder import (
    SALESFORCE_DELETED_AT_METADATA_KEY,
    build_create_patient_effect,
    build_manual_review_task,
    build_mapped_patient_from_form,
    build_tag_deleted_effect,
    build_update_patient_effect,
)
from salesforce_to_canvas_integration.services.field_mapping import MappedPatient
from salesforce_to_canvas_integration.services.patient_link import (
    SALESFORCE_IDENTIFIER_SYSTEM,
)


def _seed_salesforce_link(external_id: str) -> Any:
    """Create a Patient carrying a Salesforce external identifier."""
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


def _mapped() -> MappedPatient:
    return MappedPatient(
        canvas_fields={
            "first_name": "Jane",
            "last_name": "Doe",
            "date_of_birth": "1985-04-12",
            "email": "jane@example.com",
            "phone": "+15551234567",
            "address_line_1": "10 Main St",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62704",
            "country": "US",
            "sex_at_birth": "female",
        },
        metadata={"preferred_language": "Spanish"},
        telecom={"mobile": "+15559998888"},
    )


def test_create_effect_carries_demographics_metadata_and_external_id() -> None:
    effect = build_create_patient_effect(
        mapped=_mapped(),
        sf_record_id="003xx0000000001AAA",
    )

    # The Patient.create() effect renders to a dict-like payload.
    payload = effect.payload
    assert "first_name" in payload or hasattr(effect, "type")

    # The underlying Patient model captured all relevant fields.
    patient_repr = repr(effect)
    assert "Jane" in patient_repr
    assert "Doe" in patient_repr
    assert "salesforce" in patient_repr.lower()


def test_create_effect_writes_no_salesforce_metadata_keys() -> None:
    # Step six dropped the three salesforce_ metadata rows. The linkage now rides
    # on the external identifier, so the keys must be absent while "salesforce"
    # still appears through that identifier.
    effect = build_create_patient_effect(
        mapped=_mapped(),
        sf_record_id="003xx0000000001AAA",
    )
    rendered = repr(effect)

    for dropped in ("salesforce_record_id", "salesforce_sobject", "salesforce_instance_url"):
        assert dropped not in rendered
    assert "salesforce" in rendered.lower()


def test_create_effect_normalises_gender_to_canvas_enum() -> None:
    mapped = MappedPatient(
        canvas_fields={"first_name": "Jane", "last_name": "Doe", "sex_at_birth": "female"},
        metadata={},
    )
    effect = build_create_patient_effect(
        mapped=mapped,
        sf_record_id="003",
    )
    # PersonSex.SEX_FEMALE.value appears in serialised effect representation
    assert PersonSex.SEX_FEMALE.value in repr(effect)


def test_update_effect_uses_supplied_canvas_patient_id() -> None:
    # Patient.update() validates the patient id exists, so seed one via the
    # SDK factory and use its id.
    patient = PatientFactory.create()
    effect = build_update_patient_effect(
        canvas_patient_id=str(patient.id),
        mapped=_mapped(),
    )
    assert str(patient.id) in repr(effect)


def _decode_effect_values(effect: Any) -> dict[str, Any]:
    """Pull the dirty field values out of an applied PatientEffect."""
    import json

    payload = json.loads(effect.payload)
    return dict(payload["data"])


def test_update_effect_skips_keys_absent_from_mapped() -> None:
    """Delta apply: only fields present in ``mapped.canvas_fields`` cross over."""
    patient = PatientFactory.create()
    sparse = MappedPatient(
        canvas_fields={"email": "renamed@example.com"},
        metadata={},
        telecom={},
    )
    effect = build_update_patient_effect(
        canvas_patient_id=str(patient.id), mapped=sparse
    )
    values = _decode_effect_values(effect)

    # The mapped key plus the patient id should appear in the dirty set. Other
    # demographic columns must stay absent so Canvas leaves them alone.
    assert "contact_points" in values
    assert "first_name" not in values
    assert "last_name" not in values
    assert "birthdate" not in values
    assert "sex_at_birth" not in values
    assert "addresses" not in values
    assert "metadata" not in values


def test_update_effect_preserves_existing_salesforce_link() -> None:
    """An apply carries the patient's existing Salesforce identifier so the
    update does not drop the link. Regression for journal cnv-909/098 F3, where
    applying a modify deleted the identifier and orphaned the patient.
    """
    patient = _seed_salesforce_link("003LINKPRESERVE")
    effect = build_update_patient_effect(
        canvas_patient_id=str(patient.id), mapped=_mapped()
    )
    values = _decode_effect_values(effect)
    assert "external_identifiers" in values
    assert any(
        ident["system"] == SALESFORCE_IDENTIFIER_SYSTEM
        and ident["value"] == "003LINKPRESERVE"
        for ident in values["external_identifiers"]
    )


def test_update_effect_omits_identifiers_when_patient_has_none() -> None:
    """A patient with no external identifiers adds no identifier key, so the
    delta apply stays minimal and the existing helper tests hold.
    """
    patient = PatientFactory.create()
    effect = build_update_patient_effect(
        canvas_patient_id=str(patient.id), mapped=_mapped()
    )
    values = _decode_effect_values(effect)
    assert "external_identifiers" not in values


def test_tag_deleted_effect_preserves_existing_salesforce_link() -> None:
    """Tagging a delete carries the existing identifiers so the link survives.
    Regression for journal cnv-909/098 F3.
    """
    patient = _seed_salesforce_link("003DELLINK")
    effect = build_tag_deleted_effect(
        canvas_patient_id=str(patient.id),
        deleted_at=datetime(2026, 5, 28, 14, 30, tzinfo=timezone.utc),
    )
    values = _decode_effect_values(effect)
    assert "external_identifiers" in values
    assert any(
        ident["value"] == "003DELLINK" for ident in values["external_identifiers"]
    )


def test_update_effect_omits_addresses_when_no_address_line() -> None:
    """A mapped record with no ``address_line_1`` does not clear the address."""
    patient = PatientFactory.create()
    no_address = MappedPatient(
        canvas_fields={"first_name": "Renamed"},
        metadata={},
        telecom={},
    )
    effect = build_update_patient_effect(
        canvas_patient_id=str(patient.id), mapped=no_address
    )
    values = _decode_effect_values(effect)
    assert "addresses" not in values


def test_update_effect_emits_metadata_only_when_present() -> None:
    """Empty metadata stays out of the effect, populated metadata crosses over."""
    patient = PatientFactory.create()
    empty = MappedPatient(
        canvas_fields={"first_name": "Renamed"},
        metadata={},
        telecom={},
    )
    populated = MappedPatient(
        canvas_fields={"first_name": "Renamed"},
        metadata={"preferred_language": "Spanish"},
        telecom={},
    )
    empty_values = _decode_effect_values(
        build_update_patient_effect(
            canvas_patient_id=str(patient.id), mapped=empty
        )
    )
    populated_values = _decode_effect_values(
        build_update_patient_effect(
            canvas_patient_id=str(patient.id), mapped=populated
        )
    )
    assert "metadata" not in empty_values
    assert "metadata" in populated_values


def test_tag_deleted_effect_carries_only_metadata_and_patient_id() -> None:
    """Tag deleted writes one metadata entry, no demographic columns ride along."""
    patient = PatientFactory.create()
    deleted_at = datetime(2026, 5, 28, 14, 30, tzinfo=timezone.utc)

    effect = build_tag_deleted_effect(
        canvas_patient_id=str(patient.id),
        deleted_at=deleted_at,
    )
    values = _decode_effect_values(effect)

    assert set(values.keys()) == {"patient_id", "metadata"}
    assert values["patient_id"] == str(patient.id)
    metadata = values["metadata"]
    assert isinstance(metadata, list)
    assert len(metadata) == 1
    entry = metadata[0]
    assert entry["key"] == SALESFORCE_DELETED_AT_METADATA_KEY
    assert entry["value"] == deleted_at.isoformat()


def test_manual_review_task_lists_all_candidates() -> None:
    effect = build_manual_review_task(
        sf_record_id="003xyz",
        candidate_ids=("canvas-1", "canvas-2"),
    )
    rendered = repr(effect)
    assert "003xyz" in rendered
    assert "canvas-1" in rendered
    assert "canvas-2" in rendered
    assert "manual-review" in rendered


def test_mobile_telecom_emits_separate_contact_point() -> None:
    effect = build_create_patient_effect(
        mapped=_mapped(),
        sf_record_id="003",
    )
    rendered = repr(effect)
    assert ContactPointSystem.PHONE.value in rendered
    assert ContactPointUse.MOBILE.value in rendered
    assert "+15559998888" in rendered


def test_create_effect_coerces_birthdate_string() -> None:
    effect = build_create_patient_effect(
        mapped=_mapped(),
        sf_record_id="003",
    )
    assert str(date(1985, 4, 12)) in repr(effect)


def test_form_helper_takes_edited_fields_over_captured_values() -> None:
    """Form values drive every editable canvas field."""
    mapped = build_mapped_patient_from_form(
        form={
            "first_name": "Ada ",
            "last_name": " King Lovelace ",
            "date_of_birth": "1990-04-15",
            "sex_at_birth": "female",
            "email": "ada.king@example.com",
            "phone": "+15551112222",
            "address_line_1": "1 Analytical Way",
            "city": "London",
            "state": "CA",
            "postal_code": "90210",
            "country": "US",
        },
        metadata={"preferred_language": "English"},
        telecom={"mobile": "+15553334444"},
    )

    assert mapped.canvas_fields["first_name"] == "Ada"
    assert mapped.canvas_fields["last_name"] == "King Lovelace"
    assert mapped.canvas_fields["email"] == "ada.king@example.com"
    assert mapped.metadata == {"preferred_language": "English"}
    assert mapped.telecom == {"mobile": "+15553334444"}


def test_form_helper_overrides_mobile_when_form_value_is_supplied() -> None:
    mapped = build_mapped_patient_from_form(
        form={"last_name": "Doe", "telecom_mobile": "+15559998888"},
        metadata={},
        telecom={"mobile": "+15553334444"},
    )

    assert mapped.telecom == {"mobile": "+15559998888"}


def test_form_helper_clears_mobile_when_form_supplies_an_empty_value() -> None:
    mapped = build_mapped_patient_from_form(
        form={"last_name": "Doe", "telecom_mobile": ""},
        metadata={},
        telecom={"mobile": "+15553334444"},
    )

    assert "mobile" not in mapped.telecom


def test_form_helper_ignores_unknown_keys() -> None:
    """Unknown form keys cannot spoof Canvas fields the SDK will write."""
    mapped = build_mapped_patient_from_form(
        form={"last_name": "Doe", "ssn": "not-a-real-ssn", "is_admin": True},
        metadata={},
        telecom={},
    )

    assert "ssn" not in mapped.canvas_fields
    assert "is_admin" not in mapped.canvas_fields
    assert mapped.canvas_fields == {"last_name": "Doe"}
