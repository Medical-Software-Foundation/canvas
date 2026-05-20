"""Build the ELLKAY Orders & Results JSON v2.2 payload for a Vanta lab order.

This module is pure (no I/O, no secrets access) so it is fully unit-testable.
All inputs are Canvas SDK data-model objects or plain dicts returned by the
settings helpers.

Reference: ELLKAY Orders & Results JSON v2.2 specification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from canvas_sdk.v1.data.lab import LabOrder


ICD10_SYSTEM_PREFIXES = (
    "http://hl7.org/fhir/sid/icd-10",
    "ICD-10",
    "icd-10",
    "2.16.840.1.113883.6.90",
)

# ELLKAY Orders & Results JSON v2.2 Appendix → Ethnicity (page 35).
# Spec values: H = Hispanic Or Latino, N = Not Hispanic Or Latino, U = Unknown.
# Canvas Patient.cultural_ethnicity_codes carries CDC OMB codes; translate.
_ELLKAY_ETHNICITY_FROM_CDC = {
    "2135-2": "H",  # Hispanic or Latino
    "2186-5": "N",  # Not Hispanic or Latino
}

# ELLKAY Orders & Results JSON v2.2 Appendix → Relationship (pages 32-33).
# Canvas Coverage.patient_relationship_to_subscriber emits X12 0344
# numeric codes (e.g. "18" = Self). Map to ELLKAY 3-letter codes.
_ELLKAY_RELATIONSHIP_FROM_X12 = {
    "01": "SPO",  # Spouse
    "04": "GRP",  # Grandparent
    "05": "GCH",  # Grandchild
    "07": "OTH",  # Nephew or Niece -> Other (no exact ELLKAY code)
    "09": "CHD",  # Adopted Child -> Child
    "10": "FCH",  # Foster Child
    "15": "WRD",  # Ward
    "17": "SCH",  # Stepchild
    "18": "SEL",  # Self
    "19": "CHD",  # Child
    "20": "EME",  # Employee
    "21": "UNK",  # Unknown
    "22": "DEP",  # Handicapped Dependent
    "23": "DEP",  # Sponsored Dependent -> Handicapped Dependent (closest)
    "29": "DOM",  # Significant Other -> Life Partner
    "32": "MTH",  # Mother
    "33": "FTH",  # Father
    "36": "OTH",  # Emancipated Minor -> Other
    "39": "OTH",  # Organ Donor -> Other
    "40": "OTH",  # Cadaver Donor -> Other
    "41": "OTH",  # Injured Plaintiff -> Other
    "43": "CHD",  # Child Where Insured Has No Financial Responsibility -> Child
    "53": "DOM",  # Life Partner
    "G8": "OTH",  # Other Relationship
}


def _ellkay_ethnicity(cdc_codes: Any) -> str:
    """Translate Canvas's CDC ethnicity codes to ELLKAY's H/N/U values.

    Returns "" when no usable code is present so an empty Patient.Ethnicity
    is emitted rather than a guess.
    """
    if not cdc_codes:
        return ""
    for code in cdc_codes:
        mapped = _ELLKAY_ETHNICITY_FROM_CDC.get(str(code))
        if mapped:
            return mapped
    return "U"


def _ellkay_relationship(x12_code: Any) -> str:
    """Translate Canvas's X12 0344 relationship code to ELLKAY's 3-letter code.

    Unknown / blank inputs return "UNK" so the field always carries a valid
    Appendix value (PolicyHolderRelationshipToPatient is required).
    """
    if not x12_code:
        return "UNK"
    return _ELLKAY_RELATIONSHIP_FROM_X12.get(str(x12_code), "UNK")


# ELLKAY Orders & Results JSON v2.2 Appendix → Gender (page 32).
# Spec values: F, M, O, N, U, A. Canvas Patient.sex_at_birth uses the
# SexAtBirth enum whose serialized values vary; map both letter forms and
# common word forms defensively.
_ELLKAY_GENDER_FROM_CANVAS = {
    "F": "F", "M": "M", "O": "O", "N": "N", "U": "U", "A": "A",
    "f": "F", "m": "M", "o": "O", "n": "N", "u": "U", "a": "A",
    "female": "F",
    "male": "M",
    "other": "O",
    "not_applicable": "N",
    "unknown": "U",
    "unk": "U",
    "ambiguous": "A",
    "not_recorded": "U",
}


def _ellkay_gender(value: Any) -> str:
    """Translate Canvas's sex_at_birth value to ELLKAY's single-letter Gender code.

    Returns "" when no usable value is provided. Anything outside the appendix
    is returned as-is upstream — but the appendix is exhaustive, so any
    unrecognized Canvas value is surfaced by ELLKAY validation, which is
    what we want during integration testing.
    """
    if value is None or value == "":
        return ""
    return _ELLKAY_GENDER_FROM_CANVAS.get(str(value), str(value))


def _digits_only(value: Any) -> str:
    """Strip non-digit characters (per ELLKAY Appendix Data Formats p.31).

    Phone numbers must be 9999999999 with no separators; SSNs must be
    999999999 with no dashes. Canvas may store either dotted/dashed or
    bare values, so normalize at every emit site.
    """
    if not value:
        return ""
    return "".join(c for c in str(value) if c.isdigit())


def _normalize_icd10_code(code: Any) -> str:
    """Ensure ICD-10 codes carry the standard decimal point.

    Canvas's ConditionCoding.code may be stored either dotted (e.g. "Z11.59")
    or undotted (e.g. "Z1159"). ELLKAY's Diagnosis spec p.30 says "the actual
    ICD9 or ICD10 diagnosis code" without format guidance — virtually every
    downstream dictionary uses the dotted form, so normalize to that.

    ICD-10-CM format: [A-TV-Z] + 2 digits + optional dot + up to 4 more chars.
    The dot goes after position 3 when the code is 4+ chars long and lacks one.
    """
    s = _str(code)
    if not s or "." in s:
        return s
    if len(s) > 3 and s[0].isalpha():
        return f"{s[:3]}.{s[3:]}"
    return s


def _empty_provider_block() -> dict[str, str]:
    """Return the 8-key empty Provider object structure.

    ELLKAY Provider Object spec (p.26). The ORDERS JSON template (p.5)
    shows ReferringProvider as the full empty Provider shape even when
    not used — emit the same keys to satisfy strict parsers.
    """
    return {
        "NPI": "",
        "Code": "",
        "CodeType": "",
        "LastName": "",
        "FirstName": "",
        "MiddleName": "",
        "Suffix": "",
        "Prefix": "",
    }


def _utc_now_datetime() -> str:
    """Current UTC time as ELLKAY DateTime: yyyyMMddHHmmss (no separators)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _date_str(value: Any) -> str:
    """Return a date/datetime as yyyyMMdd (ELLKAY Date format), or empty string.

    Per ELLKAY Orders & Results JSON v2.2 Appendix → Data Formats:
        Date = yyyyMMdd (no dashes).
    """
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return str(value.strftime("%Y%m%d"))
    s = str(value)
    # Tolerate already-formatted strings: strip dashes if ISO-like.
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:4] + s[5:7] + s[8:10]
    return s[:8]


def _datetime_str(value: Any) -> str:
    """Return a datetime as yyyyMMddHHmmss (ELLKAY DateTime format), or empty string.

    Per ELLKAY Orders & Results JSON v2.2 Appendix → Data Formats:
        DateTime = yyyyMMddHHmmss (no separators).
    """
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return str(value.strftime("%Y%m%d%H%M%S"))
    return ""


def _str(value: Any) -> str:
    """Coerce to str, returning empty string for None."""
    if value is None:
        return ""
    return str(value)


def _is_icd10(system: str) -> bool:
    return any(system.startswith(prefix) for prefix in ICD10_SYSTEM_PREFIXES)


def _build_ordering_provider(lab_order: LabOrder) -> dict[str, str]:
    """Build the OrderingProvider block.

    ELLKAY Provider Object (spec p.26): Code and CodeType are required. When
    the provider has an NPI, Code carries the NPI value and CodeType is "NPI"
    (Physician Code Types appendix, p.31).
    """
    provider = lab_order.ordering_provider
    if provider is None:
        return {
            "NPI": "",
            "Code": "",
            "CodeType": "",
            "LastName": "",
            "FirstName": "",
            "MiddleName": "",
            "Suffix": "",
            "Prefix": "",
        }
    npi = _str(provider.npi_number)
    return {
        "NPI": npi,
        "Code": npi,
        "CodeType": "NPI" if npi else "",
        "LastName": _str(provider.last_name),
        "FirstName": _str(provider.first_name),
        "MiddleName": _str(provider.middle_name),
        "Suffix": _str(provider.suffix),
        "Prefix": _str(provider.prefix),
    }


def _patient_address_block(patient: Any) -> dict[str, str]:
    """Return (Address1, Address2, City, State, Zip) for a Patient.

    Prefers a 'home'-use address; falls back to the patient's first address.
    Empty strings when no address is on file. Captures the fallback during
    iteration so we never bypass the prefetch cache with a follow-up
    `.first()` call.
    """
    home_addr: Any = None
    fallback_addr: Any = None
    for addr in patient.addresses.all():
        if fallback_addr is None:
            fallback_addr = addr
        if getattr(addr, "use", None) in ("home", "H", "HOM"):
            home_addr = addr
            break
    home_addr = home_addr or fallback_addr

    if home_addr is None:
        return {"Address1": "", "Address2": "", "City": "", "State": "", "Zip": ""}

    return {
        "Address1": _str(getattr(home_addr, "line1", "")),
        "Address2": _str(getattr(home_addr, "line2", "")),
        "City": _str(getattr(home_addr, "city", "")),
        "State": _str(getattr(home_addr, "state_code", "")),
        "Zip": _str(getattr(home_addr, "postal_code", "")),
    }


def _patient_telecom(patient: Any) -> dict[str, str]:
    """Return (HomePhoneNumber, MobilePhoneNumber, WorkPhoneNumber, Email) for a Patient."""
    home_phone = mobile_phone = work_phone = email = ""
    for cp in patient.telecom.all():
        system = _str(getattr(cp, "system", "")).lower()
        use = _str(getattr(cp, "use", "")).lower()
        val = _str(cp.value)
        if system == "phone":
            # ELLKAY Appendix p.31: phones must be 9999999999 (no separators).
            digits = _digits_only(val)
            if use in ("mobile", "mc", "mob") and not mobile_phone:
                mobile_phone = digits
            elif use in ("work", "w", "wp", "business") and not work_phone:
                work_phone = digits
            elif use in ("home", "h", "hp") and not home_phone:
                home_phone = digits
            elif not home_phone:
                home_phone = digits
        elif system == "email" and not email:
            email = val
    return {
        "HomePhoneNumber": home_phone,
        "MobilePhoneNumber": mobile_phone,
        "WorkPhoneNumber": work_phone,
        "Email": email,
    }


def _build_patient(lab_order: LabOrder) -> dict[str, Any]:
    """Build the Patient block per ELLKAY spec Patient Object (p.27)."""
    patient = lab_order.patient
    addr = _patient_address_block(patient)
    tel = _patient_telecom(patient)

    return {
        "ChartNumber": _str(patient.id),
        "ExternalPatientId": _str(patient.id),
        "InternalPatientId": _str(patient.id),
        "LastName": _str(patient.last_name),
        "FirstName": _str(patient.first_name),
        "MiddleName": _str(patient.middle_name),
        "Suffix": _str(patient.suffix),
        "Prefix": _str(patient.prefix),
        "DateOfBirth": _date_str(patient.birth_date),
        # ELLKAY Gender appendix p.32: F/M/O/N/U/A single letters.
        "Gender": _ellkay_gender(patient.sex_at_birth),
        "GenderIdentity": _str(patient.gender_identity_code),
        # ELLKAY Appendix p.31: SSN must be 999999999 (no dashes).
        "SocialSecurityNumber": _digits_only(patient.social_security_number),
        "Race": _str(
            patient.biological_race_codes[0]
            if getattr(patient, "biological_race_codes", None)
            else ""
        ),
        "Address1": addr["Address1"],
        "Address2": addr["Address2"],
        "City": addr["City"],
        "State": addr["State"],
        "Zip": addr["Zip"],
        "HomePhoneNumber": tel["HomePhoneNumber"],
        "Email": tel["Email"],
        "MobilePhoneNumber": tel["MobilePhoneNumber"],
        "WorkPhoneNumber": tel["WorkPhoneNumber"],
        "Language": "",
        "MaritalStatus": "",
        "Religion": "",
        "DriverLicenseNumber": "",
        # Spec p.27 places Ethnicity after DriverLicenseNumber, before PatientDeathDateTime.
        "Ethnicity": _ellkay_ethnicity(
            getattr(patient, "cultural_ethnicity_codes", None)
        ),
        "PatientDeathDateTime": "",
        "Notes": [],
    }


def _build_guarantor(lab_order: LabOrder) -> dict[str, str]:
    """Build the Guarantor block per ELLKAY spec Guarantor Object (p.28).

    v1 treats the patient as their own guarantor (RelationshipToPatient=SEL).
    Field order and field set exactly match the spec; address and phones are
    populated from the patient.
    """
    patient = lab_order.patient
    addr = _patient_address_block(patient)
    tel = _patient_telecom(patient)

    return {
        "RelationshipToPatient": "SEL",
        "LastName": _str(patient.last_name),
        "FirstName": _str(patient.first_name),
        "MiddleName": _str(patient.middle_name),
        "Suffix": _str(patient.suffix),
        "Prefix": _str(patient.prefix),
        "Address1": addr["Address1"],
        "Address2": addr["Address2"],
        "City": addr["City"],
        "State": addr["State"],
        "Zip": addr["Zip"],
        "HomePhoneNumber": tel["HomePhoneNumber"],
        "BusinessPhoneNumber": tel["WorkPhoneNumber"],
        "DateOfBirth": _date_str(patient.birth_date),
        "Gender": _ellkay_gender(patient.sex_at_birth),
        "SocialSecurityNumber": _digits_only(patient.social_security_number),
        "GuarantorOrganizationName": "",
        "MobilePhoneNumber": tel["MobilePhoneNumber"],
    }


def _build_insurances(lab_order: LabOrder) -> list[dict[str, str]]:
    """Build the Insurances list per ELLKAY spec Insurance Object (p.28-29).

    Field order matches the spec. PolicyHolder demographics + address come
    from coverage.subscriber (which is the same Patient as the patient for
    self-pay coverages). Company address comes from coverage.issuer_address.
    BillType is 'T' (3rd Party) when insurance is present.

    NOTE: BillType codes must be confirmed with ELLKAY before go-live.
    """
    patient = lab_order.patient
    try:
        coverages = list(
            patient.coverages.select_related(
                "issuer",
                "subscriber",
                "issuer_address",
                "issuer_phone",
            )
            # Subscriber's addresses are accessed by _patient_address_block
            # below for non-self-pay coverages; prefetch them here to avoid
            # a per-coverage query.
            .prefetch_related("subscriber__addresses")
            .filter(state="active")
            .order_by("coverage_rank")
        )
    except Exception:
        coverages = []

    if not coverages:
        return []

    result = []
    for seq, coverage in enumerate(coverages, start=1):
        # Issuer (insurance company)
        company_id = ""
        company_name = ""
        if coverage.issuer is not None:
            company_id = _str(getattr(coverage.issuer, "payer_id", ""))
            company_name = _str(coverage.issuer.name)

        # Issuer address / phone are direct attributes on Coverage in Canvas
        ia = getattr(coverage, "issuer_address", None)
        i_addr1 = _str(getattr(ia, "line1", "")) if ia is not None else ""
        i_addr2 = _str(getattr(ia, "line2", "")) if ia is not None else ""
        i_city = _str(getattr(ia, "city", "")) if ia is not None else ""
        i_state = _str(getattr(ia, "state_code", "")) if ia is not None else ""
        i_zip = _str(getattr(ia, "postal_code", "")) if ia is not None else ""

        ip = getattr(coverage, "issuer_phone", None)
        # Strip separators per ELLKAY Phone format (Appendix p.31).
        i_phone = _digits_only(getattr(ip, "value", "")) if ip is not None else ""

        # Subscriber (policy holder) — Patient instance
        subscriber = coverage.subscriber if coverage.subscriber is not None else patient
        sub_addr = _patient_address_block(subscriber)

        result.append(
            {
                "SequenceNumber": str(seq),
                "PlanId": "",
                "CompanyId": company_id,
                "CompanyName": company_name,
                "Address1": i_addr1,
                "Address2": i_addr2,
                "City": i_city,
                "State": i_state,
                "Zip": i_zip,
                "PhoneNumber": i_phone,
                "GroupNumber": _str(coverage.group),
                "GroupName": _str(coverage.sub_group),
                "PolicyNumber": _str(coverage.id_number),
                "PlanEffectiveDate": _date_str(coverage.coverage_start_date),
                "PlanExpirationDate": _date_str(coverage.coverage_end_date),
                "BillType": "T",  # 3rd Party — confirm with ELLKAY (open item #2)
                "PolicyHolderRelationshipToPatient": _ellkay_relationship(
                    getattr(coverage, "patient_relationship_to_subscriber", None)
                ),
                "PolicyHolderLastName": _str(subscriber.last_name),
                "PolicyHolderFirstName": _str(subscriber.first_name),
                "PolicyHolderMiddleName": _str(subscriber.middle_name),
                "PolicyHolderSuffix": _str(subscriber.suffix),
                "PolicyHolderPrefix": _str(subscriber.prefix),
                "PolicyHolderDateOfBirth": _date_str(subscriber.birth_date),
                "PolicyHolderGender": _ellkay_gender(subscriber.sex_at_birth),
                "PolicyHolderSocialSecurityNumber": _digits_only(
                    getattr(subscriber, "social_security_number", "")
                ),
                "PolicyHolderAddress1": sub_addr["Address1"],
                "PolicyHolderAddress2": sub_addr["Address2"],
                "PolicyHolderCity": sub_addr["City"],
                "PolicyHolderState": sub_addr["State"],
                "PolicyHolderZip": sub_addr["Zip"],
            }
        )
    return result


def _build_diagnoses(lab_order: LabOrder) -> list[dict[str, str]]:
    """Return ICD-10 coded diagnoses from LabOrder.reasons → LabOrderReasonCondition."""
    diagnoses: list[dict[str, str]] = []
    seq = 1
    for reason in lab_order.reasons.prefetch_related(
        "reason_conditions__condition__codings"
    ).all():
        for reason_condition in reason.reason_conditions.all():
            condition = reason_condition.condition
            if condition is None:
                continue
            for coding in condition.codings.all():
                system = _str(getattr(coding, "system", ""))
                if _is_icd10(system):
                    diagnoses.append(
                        {
                            "SequenceNumber": str(seq),
                            # Normalize to dotted ICD-10 (e.g. Z1159 -> Z11.59).
                            "Code": _normalize_icd10_code(coding.code),
                            "Description": _str(coding.display),
                            # ELLKAY spec Diagnosis Object p.30: CodingMethod
                            # values are "ICD9" or "ICD10" (no dash).
                            "CodingMethod": "ICD10",
                        }
                    )
                    seq += 1
    return diagnoses


def _build_observation_request(
    lab_order: LabOrder,
    diagnoses: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Build one ObservationRequest entry per LabTest on the order."""
    placer = str(lab_order.id)
    note = lab_order.note
    note_id = _str(note.id) if note is not None else ""
    patient_id = _str(lab_order.patient.id)

    comment = _str(lab_order.comment)
    notes_block: list[dict[str, str]] = (
        [{"SequenceNumber": "1", "Note": comment}] if comment else []
    )

    requested_dt = _datetime_str(lab_order.date_ordered)

    tests = list(
        lab_order.tests.all()
    )

    observations = []
    for seq, test in enumerate(tests, start=1):
        observations.append(
            {
                "SequenceNumber": str(seq),
                "PlacerOrderNumber": placer,
                "FillerOrderNumber": "",
                # OrderStatus is required (spec p.29). "SC" = Scheduled per
                # Order Status Appendix p.33-34. TODO: confirm with ELLKAY
                # that "SC" is the correct status for a brand-new outbound
                # order (open item #6).
                "OrderStatus": "SC",
                "OrderControl": "NW",
                "OrderControlCodeReason": "",
                "TestCodeId": _str(test.ontology_test_code),
                "TestCodeType": "L",  # local code
                "TestCodeDescription": _str(test.ontology_test_name),
                "Priority": "R",  # routine
                "RequestedDateTime": requested_dt,
                # ObservationDateTime is required (spec p.29). For new orders
                # with no collection yet, we use the order-signed timestamp.
                # TODO: confirm with ELLKAY whether this should be the
                # expected collection time or remain order_signed (open
                # item #7).
                "ObservationDateTime": requested_dt,
                "ObservationEndDateTime": "",
                "CollectionVolume": "",
                "SpecimenReceivedDateTime": "",
                "SpecimenSource": _str(test.specimen_source_code),
                "SpecimenName": _str(test.specimen_type),
                "DiagnosticService": "",
                "ResultStatus": "",
                "ResultCopiesTo": [],
                "Diagnoses": diagnoses,
                "Notes": notes_block,
                "Custom": [
                    {"Name": "CanvasPatientId", "Value": patient_id},
                    {"Name": "CanvasOrderId", "Value": placer},
                    {"Name": "CanvasNoteId", "Value": note_id},
                ],
                "AOE": [],
            }
        )
    return observations


def build_order_payload(
    lab_order: LabOrder,
    secrets: dict[str, Any],
) -> dict[str, Any]:
    """Build the complete ELLKAY Orders JSON v2.2 envelope for a new order.

    Args:
        lab_order: Fully loaded LabOrder instance (note, patient, tests,
                   reasons, ordering_provider pre-fetched is optimal but not required).
        secrets: The plugin secrets dict (see vanta_lab_orders.settings).

    Returns:
        A dict ready to be JSON-serialised and POSTed to LKCareEvolve.

    Raises:
        KeyError: If the note's location has no account number in the map.
        ValueError: If any required secret is missing or malformed.
    """
    from vanta_lab_orders.settings import (
        account_number_for_location,
        sending_facility_name,
    )

    note = lab_order.note
    location_id = ""
    location_name = ""
    account_number = ""

    if note is not None and note.location is not None:
        location_id = str(note.location.id)
        location_name = _str(note.location.full_name)

    if location_id:
        account_number = account_number_for_location(location_id, secrets)
    else:
        raise KeyError(
            f"LabOrder {lab_order.id} has no note location — cannot resolve account number."
        )

    facility_name = sending_facility_name(secrets)
    placer = str(lab_order.id)
    diagnoses = _build_diagnoses(lab_order)
    observation_request = _build_observation_request(lab_order, diagnoses)

    return {
        "MessageHeader": {
            "SendingApplication": "Canvas Medical",
            "SendingFacilityName": facility_name,
            "ReceivingApplication": "LKCareEvolve",
            "ReceivingFacility": "Vanta Diagnostics",
            "MessageDateTime": _utc_now_datetime(),
            "MessageId": str(uuid.uuid4()),
            "AccountNumber": account_number,
            "OrderDateTime": _datetime_str(lab_order.date_ordered),
            "ResultDateTime": "",
            "PlacerOrderNumber": placer,
            "FillerOrderNumber": "",
            "LocationCode": location_id,
            "LocationName": location_name,
            "OrderingProvider": _build_ordering_provider(lab_order),
            "ReferringProvider": _empty_provider_block(),
            "Patient": _build_patient(lab_order),
            "Guarantor": _build_guarantor(lab_order),
            "Insurances": _build_insurances(lab_order),
            "ObservationRequest": observation_request,
        }
    }
