"""Unit tests for vanta_lab_orders.payload.build_order_payload.

Factories create real DB objects; the payload builder is pure so no HTTP is exercised.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from canvas_sdk.test_utils.factories import (
    CoverageFactory,
    LabOrderFactory,
    LabOrderReasonConditionFactory,
    LabOrderReasonFactory,
    LabTestFactory,
    NoteFactory,
    PatientFactory,
    PracticeLocationFactory,
    StaffFactory,
)
from canvas_sdk.v1.data.condition import Condition, ConditionCoding

from tests.conftest import LOCATION_UUID_1, LOCATION_UUID_2
from vanta_lab_orders.payload import build_order_payload


_ONSET_DATE = "2025-01-01"


def _make_condition(patient: Any, icd10_code: str, display: str) -> Any:
    """Create a Condition with one ICD-10 ConditionCoding."""
    condition = Condition.objects.create(
        patient=patient,
        deleted=False,
        onset_date=_ONSET_DATE,
        resolution_date=_ONSET_DATE,
        clinical_status="active",
        notes="",
        surgical=False,
    )
    ConditionCoding.objects.create(
        condition=condition,
        code=icd10_code,
        display=display,
        system="http://hl7.org/fhir/sid/icd-10",
    )
    return condition


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_location(location_uuid: str = LOCATION_UUID_1) -> Any:
    """Create a PracticeLocation with the given UUID string (must be valid UUID)."""
    return PracticeLocationFactory.create(id=location_uuid, full_name="Main Clinic")


def _make_lab_order(
    location_uuid: str = LOCATION_UUID_1,
    num_tests: int = 1,
    with_provider: bool = True,
    with_comment: bool = True,
) -> Any:
    """Create a LabOrder with associated tests and optional ordering provider."""
    location = _make_location(location_uuid)
    note = NoteFactory.create(location=location)
    provider = StaffFactory.create(npi_number="1234567890") if with_provider else None
    lab_order = LabOrderFactory.create(
        note=note,
        patient=note.patient,
        ordering_provider=provider,
        comment="Please process urgently." if with_comment else "",
    )
    for _ in range(num_tests):
        LabTestFactory.create(order=lab_order)
    return lab_order


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_happy_path_single_test(secrets: dict) -> None:
    """Full happy path: single test, one ICD-10 reason, no insurance."""
    lab_order = _make_lab_order(num_tests=1)

    # Add an ICD-10 reason
    condition = _make_condition(lab_order.patient, "J06.9", "Acute upper respiratory infection")
    reason = LabOrderReasonFactory.create(order=lab_order)
    LabOrderReasonConditionFactory.create(reason=reason, condition=condition)

    result = build_order_payload(lab_order, secrets)
    header = result["MessageHeader"]

    assert header["SendingApplication"] == "Canvas Medical"
    assert header["SendingFacilityName"] == "Example Facility"
    assert header["ReceivingApplication"] == "LKCareEvolve"
    assert header["ReceivingFacility"] == "Vanta Diagnostics"
    assert header["AccountNumber"] == "ACCT-001"
    assert header["PlacerOrderNumber"] == str(lab_order.id)

    # Patient block
    patient = lab_order.patient
    assert header["Patient"]["LastName"] == patient.last_name
    assert header["Patient"]["FirstName"] == patient.first_name
    assert header["Patient"]["ChartNumber"] == str(patient.id)

    # ObservationRequest
    obs = header["ObservationRequest"]
    assert len(obs) == 1
    assert obs[0]["OrderControl"] == "NW"
    assert obs[0]["PlacerOrderNumber"] == str(lab_order.id)

    # ICD-10 diagnosis
    assert obs[0]["Diagnoses"][0]["Code"] == "J06.9"
    assert obs[0]["Diagnoses"][0]["CodingMethod"] == "ICD10"

    # Custom cross-reference block
    custom_names = {c["Name"]: c["Value"] for c in obs[0]["Custom"]}
    assert custom_names["CanvasPatientId"] == str(patient.id)
    assert custom_names["CanvasOrderId"] == str(lab_order.id)
    assert custom_names["CanvasNoteId"] == str(lab_order.note.id)


@pytest.mark.django_db
def test_multi_test_order(secrets: dict) -> None:
    """Multi-test order produces one ObservationRequest per test."""
    lab_order = _make_lab_order(num_tests=3)
    result = build_order_payload(lab_order, secrets)
    obs = result["MessageHeader"]["ObservationRequest"]
    assert len(obs) == 3
    for i, entry in enumerate(obs, start=1):
        assert entry["SequenceNumber"] == str(i)
        assert entry["PlacerOrderNumber"] == str(lab_order.id)


@pytest.mark.django_db
def test_multiple_icd10_reasons(secrets: dict) -> None:
    """Multiple ICD-10 reasons appear as multiple Diagnoses entries."""
    lab_order = _make_lab_order(num_tests=1)

    reason = LabOrderReasonFactory.create(order=lab_order)
    for code, display in [
        ("Z00.00", "Encounter for general adult medical exam"),
        ("E11.9", "Type 2 diabetes"),
    ]:
        condition = _make_condition(lab_order.patient, code, display)
        LabOrderReasonConditionFactory.create(reason=reason, condition=condition)

    result = build_order_payload(lab_order, secrets)
    diagnoses = result["MessageHeader"]["ObservationRequest"][0]["Diagnoses"]
    codes = [d["Code"] for d in diagnoses]
    assert "Z00.00" in codes
    assert "E11.9" in codes
    assert all(d["CodingMethod"] == "ICD10" for d in diagnoses)


@pytest.mark.django_db
def test_non_icd10_codings_excluded(secrets: dict) -> None:
    """SNOMED-CT codings are excluded from Diagnoses; only ICD-10 is included."""
    lab_order = _make_lab_order(num_tests=1)

    # One condition with both SNOMED (excluded) and ICD-10 (included) codings
    condition = Condition.objects.create(
        patient=lab_order.patient,
        deleted=False,
        onset_date=_ONSET_DATE,
        resolution_date=_ONSET_DATE,
        clinical_status="active",
        notes="",
        surgical=False,
    )
    ConditionCoding.objects.create(
        condition=condition,
        code="444814009",
        display="Viral sinusitis",
        system="http://snomed.info/sct",
    )
    ConditionCoding.objects.create(
        condition=condition,
        code="J32.9",
        display="Chronic sinusitis, unspecified",
        system="http://hl7.org/fhir/sid/icd-10",
    )
    reason = LabOrderReasonFactory.create(order=lab_order)
    LabOrderReasonConditionFactory.create(reason=reason, condition=condition)

    result = build_order_payload(lab_order, secrets)
    diagnoses = result["MessageHeader"]["ObservationRequest"][0]["Diagnoses"]
    assert len(diagnoses) == 1
    assert diagnoses[0]["Code"] == "J32.9"


@pytest.mark.django_db
def test_missing_optional_fields_no_middle_name_no_email(secrets: dict) -> None:
    """Order with a patient who has no middle name, no email, no phone succeeds."""
    location = _make_location(LOCATION_UUID_1)
    note = NoteFactory.create(location=location)
    patient = note.patient
    patient.middle_name = ""
    patient.suffix = ""
    patient.prefix = ""
    patient.save()
    # Remove all contact points
    patient.telecom.all().delete()

    lab_order = LabOrderFactory.create(note=note, patient=patient)
    LabTestFactory.create(order=lab_order)

    result = build_order_payload(lab_order, secrets)
    p_block = result["MessageHeader"]["Patient"]
    assert p_block["MiddleName"] == ""
    assert p_block["HomePhoneNumber"] == ""
    assert p_block["Email"] == ""


@pytest.mark.django_db
def test_missing_location_account_number_raises(secrets: dict) -> None:
    """LabOrder whose location UUID is not in the map raises KeyError."""
    unmapped_uuid = "99999999-9999-9999-9999-999999999999"
    lab_order = _make_lab_order(location_uuid=unmapped_uuid)

    with pytest.raises(KeyError, match="No LKCareEvolve account number configured"):
        build_order_payload(lab_order, secrets)


@pytest.mark.django_db
def test_ordering_provider_npi_in_payload(secrets: dict) -> None:
    """OrderingProvider NPI is correctly populated from Staff.npi_number."""
    location = _make_location(LOCATION_UUID_1)
    note = NoteFactory.create(location=location)
    provider = StaffFactory.create(npi_number="9876543210", first_name="Jane", last_name="Doe")
    lab_order = LabOrderFactory.create(note=note, patient=note.patient, ordering_provider=provider)
    LabTestFactory.create(order=lab_order)

    result = build_order_payload(lab_order, secrets)
    op = result["MessageHeader"]["OrderingProvider"]
    assert op["NPI"] == "9876543210"
    assert op["LastName"] == "Doe"
    assert op["FirstName"] == "Jane"


@pytest.mark.django_db
def test_no_ordering_provider_produces_empty_npi(secrets: dict) -> None:
    """When ordering_provider is None, OrderingProvider block has empty NPI."""
    location = _make_location(LOCATION_UUID_1)
    note = NoteFactory.create(location=location)
    lab_order = LabOrderFactory.create(note=note, patient=note.patient, ordering_provider=None)
    LabTestFactory.create(order=lab_order)

    result = build_order_payload(lab_order, secrets)
    assert result["MessageHeader"]["OrderingProvider"]["NPI"] == ""


@pytest.mark.django_db
def test_insurance_populated_from_active_coverage(secrets: dict) -> None:
    """Active coverage is reflected in the Insurances block."""
    lab_order = _make_lab_order(num_tests=1)

    CoverageFactory.create(
        patient=lab_order.patient,
        id_number="POL-123456",
        group="GRP-99",
        coverage_rank=1,
        state="active",
    )

    result = build_order_payload(lab_order, secrets)
    insurances = result["MessageHeader"]["Insurances"]
    assert len(insurances) >= 1
    policy_numbers = [ins["PolicyNumber"] for ins in insurances]
    assert "POL-123456" in policy_numbers


@pytest.mark.django_db
def test_no_insurance_produces_empty_list(secrets: dict) -> None:
    """No active coverage → empty Insurances list."""
    lab_order = _make_lab_order(num_tests=1)
    # Ensure no coverages
    lab_order.patient.coverages.all().delete()

    result = build_order_payload(lab_order, secrets)
    assert result["MessageHeader"]["Insurances"] == []


@pytest.mark.django_db
def test_comment_appears_in_notes_block(secrets: dict) -> None:
    """A non-empty comment on the lab order appears in Notes on each ObservationRequest."""
    lab_order = _make_lab_order(num_tests=1, with_comment=True)
    result = build_order_payload(lab_order, secrets)
    notes = result["MessageHeader"]["ObservationRequest"][0]["Notes"]
    assert len(notes) == 1
    assert notes[0]["Note"] == lab_order.comment


@pytest.mark.django_db
def test_empty_comment_produces_empty_notes_block(secrets: dict) -> None:
    """An empty comment → empty Notes list on ObservationRequest."""
    lab_order = _make_lab_order(num_tests=1, with_comment=False)
    result = build_order_payload(lab_order, secrets)
    notes = result["MessageHeader"]["ObservationRequest"][0]["Notes"]
    assert notes == []


@pytest.mark.django_db
def test_message_id_is_unique_uuid(secrets: dict) -> None:
    """Each call generates a fresh MessageId UUID."""
    lab_order = _make_lab_order(num_tests=1)
    r1 = build_order_payload(lab_order, secrets)
    r2 = build_order_payload(lab_order, secrets)
    mid1 = r1["MessageHeader"]["MessageId"]
    mid2 = r2["MessageHeader"]["MessageId"]
    # Valid UUIDs
    uuid.UUID(mid1)
    uuid.UUID(mid2)
    # Unique per call
    assert mid1 != mid2


@pytest.mark.django_db
def test_ordering_provider_code_and_codetype_populated_from_npi(secrets: dict) -> None:
    """ELLKAY Provider Object: Code = NPI value, CodeType = 'NPI' when NPI present."""
    location = _make_location(LOCATION_UUID_1)
    note = NoteFactory.create(location=location)
    provider = StaffFactory.create(npi_number="9876543210", first_name="Jane", last_name="Doe")
    lab_order = LabOrderFactory.create(note=note, patient=note.patient, ordering_provider=provider)
    LabTestFactory.create(order=lab_order)

    op = build_order_payload(lab_order, secrets)["MessageHeader"]["OrderingProvider"]
    assert op["NPI"] == "9876543210"
    assert op["Code"] == "9876543210"
    assert op["CodeType"] == "NPI"


@pytest.mark.django_db
def test_ordering_provider_with_no_npi_leaves_code_and_codetype_empty(secrets: dict) -> None:
    """No NPI on the provider → Code and CodeType stay empty (don't fabricate a CodeType)."""
    location = _make_location(LOCATION_UUID_1)
    note = NoteFactory.create(location=location)
    provider = StaffFactory.create(npi_number="", first_name="No", last_name="NPI")
    lab_order = LabOrderFactory.create(note=note, patient=note.patient, ordering_provider=provider)
    LabTestFactory.create(order=lab_order)

    op = build_order_payload(lab_order, secrets)["MessageHeader"]["OrderingProvider"]
    assert op["NPI"] == ""
    assert op["Code"] == ""
    assert op["CodeType"] == ""


@pytest.mark.django_db
def test_diagnosis_coding_method_is_ICD10_no_dash(secrets: dict) -> None:
    """ELLKAY Diagnosis spec: CodingMethod = 'ICD10' (no dash)."""
    lab_order = _make_lab_order(num_tests=1)
    condition = _make_condition(lab_order.patient, "E11.9", "Type 2 diabetes")
    reason = LabOrderReasonFactory.create(order=lab_order)
    LabOrderReasonConditionFactory.create(reason=reason, condition=condition)

    diagnoses = build_order_payload(lab_order, secrets)["MessageHeader"][
        "ObservationRequest"
    ][0]["Diagnoses"]
    assert diagnoses[0]["CodingMethod"] == "ICD10"


@pytest.mark.django_db
def test_ethnicity_cdc_2186_5_maps_to_N(secrets: dict) -> None:
    """ELLKAY Ethnicity appendix: H/N/U. CDC 2186-5 (Not Hispanic) -> 'N'."""
    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.cultural_ethnicity_codes = ["2186-5"]
    lab_order.patient.save()
    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["Ethnicity"] == "N"


@pytest.mark.django_db
def test_ethnicity_cdc_2135_2_maps_to_H(secrets: dict) -> None:
    """CDC 2135-2 (Hispanic or Latino) -> 'H'."""
    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.cultural_ethnicity_codes = ["2135-2"]
    lab_order.patient.save()
    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["Ethnicity"] == "H"


@pytest.mark.django_db
def test_ethnicity_unknown_cdc_code_maps_to_U(secrets: dict) -> None:
    """An unrecognized CDC code maps to 'U' (Unknown) rather than passing through."""
    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.cultural_ethnicity_codes = ["9999-9"]
    lab_order.patient.save()
    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["Ethnicity"] == "U"


@pytest.mark.django_db
def test_ethnicity_empty_codes_emits_empty_string(secrets: dict) -> None:
    """No ethnicity code on patient -> empty string (no guess)."""
    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.cultural_ethnicity_codes = []
    lab_order.patient.save()
    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["Ethnicity"] == ""


@pytest.mark.django_db
def test_guarantor_relationship_to_patient_is_SEL(secrets: dict) -> None:
    """Self-pay guarantor block uses ELLKAY Relationship code 'SEL', not 'Self'."""
    lab_order = _make_lab_order(num_tests=1)
    g = build_order_payload(lab_order, secrets)["MessageHeader"]["Guarantor"]
    assert g["RelationshipToPatient"] == "SEL"


@pytest.mark.django_db
def test_insurance_policy_holder_relationship_x12_to_ellkay_code(secrets: dict) -> None:
    """Canvas X12 0344 relationship code on Coverage -> ELLKAY 3-letter code."""
    lab_order = _make_lab_order(num_tests=1)

    # X12 "18" = Self -> ELLKAY "SEL"
    CoverageFactory.create(
        patient=lab_order.patient,
        id_number="POL-X",
        coverage_rank=1,
        state="active",
        patient_relationship_to_subscriber="18",
    )

    ins = build_order_payload(lab_order, secrets)["MessageHeader"]["Insurances"]
    assert ins[0]["PolicyHolderRelationshipToPatient"] == "SEL"


@pytest.mark.django_db
def test_insurance_unknown_relationship_x12_maps_to_UNK(secrets: dict) -> None:
    """Unknown X12 relationship code falls back to ELLKAY 'UNK', never blank."""
    lab_order = _make_lab_order(num_tests=1)
    CoverageFactory.create(
        patient=lab_order.patient,
        id_number="POL-Y",
        coverage_rank=1,
        state="active",
        patient_relationship_to_subscriber="ZZ",
    )
    ins = build_order_payload(lab_order, secrets)["MessageHeader"]["Insurances"]
    assert ins[0]["PolicyHolderRelationshipToPatient"] == "UNK"


@pytest.mark.django_db
def test_guarantor_field_set_and_order_match_spec(secrets: dict) -> None:
    """Guarantor block must contain exactly the keys defined by ELLKAY spec p.28,
    in spec order. No extra keys (Email, WorkPhoneNumber) and none missing."""
    lab_order = _make_lab_order(num_tests=1)
    g = build_order_payload(lab_order, secrets)["MessageHeader"]["Guarantor"]
    assert list(g.keys()) == [
        "RelationshipToPatient",
        "LastName",
        "FirstName",
        "MiddleName",
        "Suffix",
        "Prefix",
        "Address1",
        "Address2",
        "City",
        "State",
        "Zip",
        "HomePhoneNumber",
        "BusinessPhoneNumber",
        "DateOfBirth",
        "Gender",
        "SocialSecurityNumber",
        "GuarantorOrganizationName",
        "MobilePhoneNumber",
    ], list(g.keys())


@pytest.mark.django_db
def test_guarantor_self_pay_mirrors_patient_address(secrets: dict) -> None:
    """For self-pay (SEL), Guarantor address fields come from the patient address."""
    from canvas_sdk.test_utils.factories import PatientAddressFactory

    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.addresses.all().delete()
    PatientAddressFactory.create(
        patient=lab_order.patient,
        line1="123 Main St",
        city="Boston",
        state_code="MA",
        postal_code="02118",
        use="home",
    )

    g = build_order_payload(lab_order, secrets)["MessageHeader"]["Guarantor"]
    assert g["Address1"] == "123 Main St"
    assert g["City"] == "Boston"
    assert g["State"] == "MA"
    assert g["Zip"] == "02118"


@pytest.mark.django_db
def test_insurance_field_set_and_order_match_spec(secrets: dict) -> None:
    """Insurance block must contain exactly the keys from ELLKAY spec p.28-29,
    in spec order. Includes PlanId, CompanyId, PhoneNumber, all PolicyHolder*
    fields including address."""
    lab_order = _make_lab_order(num_tests=1)
    CoverageFactory.create(
        patient=lab_order.patient,
        id_number="POL-1",
        coverage_rank=1,
        state="active",
    )

    ins = build_order_payload(lab_order, secrets)["MessageHeader"]["Insurances"][0]
    assert list(ins.keys()) == [
        "SequenceNumber",
        "PlanId",
        "CompanyId",
        "CompanyName",
        "Address1",
        "Address2",
        "City",
        "State",
        "Zip",
        "PhoneNumber",
        "GroupNumber",
        "GroupName",
        "PolicyNumber",
        "PlanEffectiveDate",
        "PlanExpirationDate",
        "BillType",
        "PolicyHolderRelationshipToPatient",
        "PolicyHolderLastName",
        "PolicyHolderFirstName",
        "PolicyHolderMiddleName",
        "PolicyHolderSuffix",
        "PolicyHolderPrefix",
        "PolicyHolderDateOfBirth",
        "PolicyHolderGender",
        "PolicyHolderSocialSecurityNumber",
        "PolicyHolderAddress1",
        "PolicyHolderAddress2",
        "PolicyHolderCity",
        "PolicyHolderState",
        "PolicyHolderZip",
    ], list(ins.keys())


@pytest.mark.django_db
def test_insurance_policy_holder_self_pay_address_from_patient(secrets: dict) -> None:
    """When subscriber == patient (self-pay), PolicyHolderAddress fields mirror patient."""
    from canvas_sdk.test_utils.factories import PatientAddressFactory

    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.addresses.all().delete()
    PatientAddressFactory.create(
        patient=lab_order.patient,
        line1="500 Oak Ave",
        city="Greenville",
        state_code="SC",
        postal_code="29607",
        use="home",
    )
    # Self-pay coverage — subscriber is the patient.
    CoverageFactory.create(
        patient=lab_order.patient,
        subscriber=lab_order.patient,
        id_number="POL-S",
        coverage_rank=1,
        state="active",
        patient_relationship_to_subscriber="18",
    )

    ins = build_order_payload(lab_order, secrets)["MessageHeader"]["Insurances"][0]
    assert ins["PolicyHolderAddress1"] == "500 Oak Ave"
    assert ins["PolicyHolderCity"] == "Greenville"
    assert ins["PolicyHolderState"] == "SC"
    assert ins["PolicyHolderZip"] == "29607"
    assert ins["PolicyHolderRelationshipToPatient"] == "SEL"


@pytest.mark.django_db
def test_patient_field_order_places_ethnicity_after_driverlicense(secrets: dict) -> None:
    """ELLKAY spec p.27 places Ethnicity between DriverLicenseNumber and PatientDeathDateTime."""
    lab_order = _make_lab_order(num_tests=1)
    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    keys = list(p.keys())
    assert keys.index("DriverLicenseNumber") < keys.index("Ethnicity")
    assert keys.index("Ethnicity") < keys.index("PatientDeathDateTime")


@pytest.mark.django_db
def test_referring_provider_is_full_empty_provider_struct(secrets: dict) -> None:
    """ReferringProvider must be the 8-key Provider shape (per spec template p.5),
    not an empty {} object."""
    lab_order = _make_lab_order(num_tests=1)
    rp = build_order_payload(lab_order, secrets)["MessageHeader"]["ReferringProvider"]
    assert list(rp.keys()) == [
        "NPI",
        "Code",
        "CodeType",
        "LastName",
        "FirstName",
        "MiddleName",
        "Suffix",
        "Prefix",
    ]
    assert all(v == "" for v in rp.values())


@pytest.mark.django_db
def test_icd10_code_is_normalized_to_dotted_form(secrets: dict) -> None:
    """ICD-10 codes stored undotted in Canvas must be emitted as dotted form."""
    lab_order = _make_lab_order(num_tests=1)
    # Canvas-side: undotted code
    condition = _make_condition(lab_order.patient, "Z1159", "Screening")
    reason = LabOrderReasonFactory.create(order=lab_order)
    LabOrderReasonConditionFactory.create(reason=reason, condition=condition)

    diagnoses = build_order_payload(lab_order, secrets)["MessageHeader"][
        "ObservationRequest"
    ][0]["Diagnoses"]
    assert diagnoses[0]["Code"] == "Z11.59"


@pytest.mark.django_db
def test_icd10_code_already_dotted_passes_through(secrets: dict) -> None:
    """Codes that already have a dot are left alone."""
    lab_order = _make_lab_order(num_tests=1)
    condition = _make_condition(lab_order.patient, "J06.9", "Acute upper resp")
    reason = LabOrderReasonFactory.create(order=lab_order)
    LabOrderReasonConditionFactory.create(reason=reason, condition=condition)

    diagnoses = build_order_payload(lab_order, secrets)["MessageHeader"][
        "ObservationRequest"
    ][0]["Diagnoses"]
    assert diagnoses[0]["Code"] == "J06.9"


@pytest.mark.django_db
def test_ssn_dashes_are_stripped(secrets: dict) -> None:
    """ELLKAY Appendix p.31: SSN must be 999999999 (no dashes)."""
    lab_order = _make_lab_order(num_tests=1)
    lab_order.patient.social_security_number = "123-45-6789"
    lab_order.patient.save()

    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["SocialSecurityNumber"] == "123456789"


@pytest.mark.django_db
def test_gender_lowercase_word_maps_to_letter(secrets: dict) -> None:
    """Canvas may emit 'male'/'female' words; ELLKAY appendix wants single letters."""
    lab_order = _make_lab_order(num_tests=1)
    # Force a word-form Gender value into the patient
    lab_order.patient.sex_at_birth = "male"
    lab_order.patient.save()

    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["Gender"] == "M"


@pytest.mark.django_db
def test_observation_request_order_status_defaults_to_SC(secrets: dict) -> None:
    """ELLKAY spec p.29: OrderStatus is required. v1 defaults to 'SC' (Scheduled).
    TODO at top of payload module references ELLKAY confirmation (open item #6)."""
    lab_order = _make_lab_order(num_tests=1)
    obs = build_order_payload(lab_order, secrets)["MessageHeader"]["ObservationRequest"][0]
    assert obs["OrderStatus"] == "SC"


@pytest.mark.django_db
def test_observation_request_observation_datetime_mirrors_requested(secrets: dict) -> None:
    """ELLKAY spec p.29: ObservationDateTime is required. For new orders we
    mirror RequestedDateTime (no separate collection time yet)."""
    lab_order = _make_lab_order(num_tests=1)
    obs = build_order_payload(lab_order, secrets)["MessageHeader"]["ObservationRequest"][0]
    assert obs["ObservationDateTime"] != ""
    assert obs["ObservationDateTime"] == obs["RequestedDateTime"]


@pytest.mark.django_db
def test_dates_use_ellkay_yyyymmdd_format(secrets: dict) -> None:
    """All Date fields must be yyyyMMdd (no dashes) per ELLKAY spec Appendix."""
    lab_order = _make_lab_order(num_tests=1)
    # Set a known DOB on the patient so we can assert exact format.
    lab_order.patient.birth_date = "1975-08-21"
    lab_order.patient.save()

    CoverageFactory.create(
        patient=lab_order.patient,
        id_number="POL-1",
        coverage_rank=1,
        state="active",
        coverage_start_date="2020-01-15",
    )

    result = build_order_payload(lab_order, secrets)
    p = result["MessageHeader"]["Patient"]
    assert p["DateOfBirth"] == "19750821", p["DateOfBirth"]

    g = result["MessageHeader"]["Guarantor"]
    assert g["DateOfBirth"] == "19750821", g["DateOfBirth"]

    insurance = result["MessageHeader"]["Insurances"][0]
    assert insurance["PlanEffectiveDate"] == "20200115", insurance["PlanEffectiveDate"]


@pytest.mark.django_db
def test_datetimes_use_ellkay_yyyymmddhhmmss_format(secrets: dict) -> None:
    """All DateTime fields must be yyyyMMddHHmmss (14 digits) per ELLKAY spec Appendix."""
    import re

    lab_order = _make_lab_order(num_tests=1)
    result = build_order_payload(lab_order, secrets)
    header = result["MessageHeader"]

    # MessageDateTime: 14 digits exactly
    assert re.fullmatch(r"\d{14}", header["MessageDateTime"]), header["MessageDateTime"]

    # OrderDateTime: 14 digits when present
    if header["OrderDateTime"]:
        assert re.fullmatch(r"\d{14}", header["OrderDateTime"]), header["OrderDateTime"]

    # ObservationRequest RequestedDateTime: 14 digits when present
    requested = header["ObservationRequest"][0]["RequestedDateTime"]
    if requested:
        assert re.fullmatch(r"\d{14}", requested), requested


def test_normalize_icd10_short_code_passes_through() -> None:
    """Codes 3 chars or shorter (no decimal expected) pass through unchanged."""
    from vanta_lab_orders.payload import _normalize_icd10_code

    assert _normalize_icd10_code("A00") == "A00"
    assert _normalize_icd10_code("") == ""
    assert _normalize_icd10_code(None) == ""


def test_normalize_icd10_purely_numeric_passes_through() -> None:
    """A non-letter-prefixed code (defensive guard) is left alone."""
    from vanta_lab_orders.payload import _normalize_icd10_code

    assert _normalize_icd10_code("12345") == "12345"


def test_ellkay_ethnicity_falls_back_to_U_when_codes_unrecognized() -> None:
    """Unknown CDC code in a non-empty list -> 'U' (Unknown)."""
    from vanta_lab_orders.payload import _ellkay_ethnicity

    assert _ellkay_ethnicity(["foobar"]) == "U"


def test_ellkay_gender_passthrough_for_unknown_value() -> None:
    """Inputs outside the map return as str(value) — surfaces during testing."""
    from vanta_lab_orders.payload import _ellkay_gender

    assert _ellkay_gender("XX") == "XX"
    assert _ellkay_gender("") == ""
    assert _ellkay_gender(None) == ""


def test_digits_only_handles_inputs() -> None:
    """Empty / None / messy inputs are normalized to digits only."""
    from vanta_lab_orders.payload import _digits_only

    assert _digits_only("") == ""
    assert _digits_only(None) == ""
    assert _digits_only("(617) 555-0100") == "6175550100"
    assert _digits_only("123-45-6789") == "123456789"


def test_date_str_handles_string_inputs() -> None:
    """ISO-like strings get dashes stripped; other strings are truncated."""
    from vanta_lab_orders.payload import _date_str

    assert _date_str("2024-12-31") == "20241231"
    assert _date_str(None) == ""
    assert _date_str("20240101extra") == "20240101"


def test_datetime_str_handles_none_and_string_inputs() -> None:
    """Non-strftime inputs return empty string."""
    from vanta_lab_orders.payload import _datetime_str

    assert _datetime_str(None) == ""
    assert _datetime_str("some-string") == ""


@pytest.mark.django_db
def test_telecom_picks_up_work_phone_and_email(secrets: dict) -> None:
    """_patient_telecom maps work/business phone and email."""
    from canvas_sdk.v1.data.patient import PatientContactPoint

    lab_order = _make_lab_order(num_tests=1)
    patient = lab_order.patient
    patient.telecom.all().delete()
    PatientContactPoint.objects.create(
        patient=patient,
        system="phone",
        use="work",
        value="617-555-0199",
        rank=1,
        has_consent=False,
        opted_out=False,
    )
    PatientContactPoint.objects.create(
        patient=patient,
        system="email",
        use="home",
        value="john@example.com",
        rank=2,
        has_consent=False,
        opted_out=False,
    )

    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["WorkPhoneNumber"] == "6175550199"
    assert p["Email"] == "john@example.com"


@pytest.mark.django_db
def test_telecom_phone_without_use_falls_back_to_home(secrets: dict) -> None:
    """A phone with no 'use' set still populates HomePhoneNumber."""
    from canvas_sdk.v1.data.patient import PatientContactPoint

    lab_order = _make_lab_order(num_tests=1)
    patient = lab_order.patient
    patient.telecom.all().delete()
    PatientContactPoint.objects.create(
        patient=patient,
        system="phone",
        use="",
        value="5555550199",
        rank=1,
        has_consent=False,
        opted_out=False,
    )

    p = build_order_payload(lab_order, secrets)["MessageHeader"]["Patient"]
    assert p["HomePhoneNumber"] == "5555550199"


@pytest.mark.django_db
def test_payload_is_json_serialisable(secrets: dict) -> None:
    """The returned dict must be JSON-serialisable (no datetime objects, etc.)."""
    lab_order = _make_lab_order(num_tests=2)
    result = build_order_payload(lab_order, secrets)
    # Should not raise
    json.dumps(result)
