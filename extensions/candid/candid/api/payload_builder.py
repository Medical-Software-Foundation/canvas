"""Build a Candid Health `/encounters/v4` request payload from a Canvas Claim.

This is a port of `prepare_claim_submission_payload` from
`candid_integration/tasks.py`, rewritten to use Canvas SDK data model
relationships instead of a raw SQL query.

See: https://docs.joincandidhealth.com/api-reference/encounters/v-4/create
"""

from typing import Any
from zoneinfo import ZoneInfo

from canvas_sdk.v1.data import Claim, ClaimCoverage

from candid.effect_helpers import active_coverages_ordered

DEFAULT_TZ = ZoneInfo("US/Central")

CANVAS = "CANVAS"
TELEHEALTH_PLACES_OF_SERVICE = {"02", "10"}

MAX_DIAGNOSES_PER_ENCOUNTER = 12
MAX_DIAGNOSIS_POINTERS_PER_SERVICE_LINE = 4
OVERFLOW_CPT_CODE = "99499"
OVERFLOW_CHARGE_CENTS = 1  # $0.01 — some payers reject $0.00 as "missing charge"

CANVAS_SEX_TO_CANDID_GENDER = {
    "F": "female",
    "M": "male",
    "O": "other",
    "UNK": "unknown",
    "": "not_given",
}


def _gender(canvas_sex: str | None) -> str:
    """Map a Canvas sex-at-birth value to Candid's gender enum."""
    return CANVAS_SEX_TO_CANDID_GENDER.get(canvas_sex or "", "unknown")


def _strip_none(value: Any) -> Any:
    """Recursively remove None values from dicts and lists."""
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value if v is not None]
    return value


def _deep_copy(value: Any) -> Any:
    """Deep-copy a JSON-serializable structure. The `copy` module is not
    available in the plugins sandbox."""
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _split_zip(zip_code: str | None) -> tuple[str, str]:
    """Split a 9-digit zip into (5-digit, 4-digit) parts."""
    if not zip_code:
        return "", ""
    clean = zip_code.replace("-", "")
    if len(clean) >= 9:
        return clean[:5], clean[5:9]
    return clean[:5], ""


def build_claim_payload(
    claim: Claim, tz: ZoneInfo | None = None
) -> tuple[dict, list[str]]:
    """Build the Candid claim submission payload from a Claim model.

    ``tz`` is the instance's configured time zone (from
    ``self.environment["INSTALLATION_TIME_ZONE"]``). Falls back to US/Central
    for backwards compatibility with the home-app's hardcoded CST conversion.

    Returns (payload, error_messages). If error_messages is non-empty, the
    caller should NOT submit the payload and should surface the errors to the
    user (e.g. via a claim comment).
    """
    errors: list[str] = []
    payload: dict[str, Any] = {
        "benefits_assigned_to_provider": True,
        "billable_status": "BILLABLE",
        "patient_authorized_release": True,
    }

    instance_tz = tz or DEFAULT_TZ

    for label, step_fn in (
        ("core fields", lambda c, p, e: _add_core_fields(c, p, e, instance_tz)),
        ("diagnoses", lambda c, p, e: _add_diagnoses(c, p, e)),
        ("service lines", lambda c, p, e: _add_service_lines(c, p)),
        ("patient", lambda c, p, e: _add_patient(c, p, e)),
        ("billing provider", lambda c, p, e: _add_billing_provider(c, p, e)),
        ("rendering provider", lambda c, p, e: _add_rendering_provider(c, p, e)),
        ("service facility", lambda c, p, e: _add_service_facility(c, p, e)),
        ("subscribers", lambda c, p, e: _add_subscribers(c, p, e)),
    ):
        try:
            step_fn(claim, payload, errors)
        except Exception as e:
            errors.append(f"Unexpected error building {label}: {e}")

    return _strip_none(payload), errors


def build_split_payloads(
    claim: Claim, tz: ZoneInfo | None = None
) -> list[tuple[dict, list[str]]]:
    """Build one or more Candid encounter payloads, splitting if >12 diagnoses.

    Claims with ≤12 diagnoses produce a single payload (unchanged behavior).
    Claims with >12 diagnoses are split into a primary claim carrying the real
    service lines and up to 12 diagnoses, plus supplemental claims carrying the
    remaining diagnoses under a 99499 CPT code at $0.01.

    Diagnoses are split in rank order (first 12, next 12, etc.) without
    reordering. The Canvas UI already provides a Claim Review Records (CRR)
    workflow where users can review and assign diagnoses across splits before
    submission, so the plugin assumes the user has approved the ordering.

    Returns a list of ``(payload, errors)`` tuples, one per split.
    """
    payload, errors = build_claim_payload(claim, tz=tz)
    if errors:
        return [(payload, errors)]

    diagnoses = payload.get("diagnoses", [])
    if len(diagnoses) <= MAX_DIAGNOSES_PER_ENCOUNTER:
        return [(payload, errors)]

    service_lines = payload.get("service_lines", [])
    chunks = _split_diagnoses(diagnoses)
    base_external_id = payload.get("external_id", "")

    payloads: list[tuple[dict, list[str]]] = []
    for split_index, chunk in enumerate(chunks):
        split_payload = _deep_copy(payload)
        split_num = split_index + 1
        split_payload["external_id"] = f"{base_external_id}-{split_num}"

        # Re-format diagnosis codes: first in each split is ABK, rest ABF
        split_payload["diagnoses"] = _format_diagnosis_chunk(chunk)

        if split_index == 0:
            # Primary: keep original service lines, drop pointers beyond index 11
            split_payload["service_lines"] = _clamp_service_line_pointers(
                service_lines, max_index=MAX_DIAGNOSES_PER_ENCOUNTER - 1
            )
        else:
            # Supplemental: single 99499 line pointing to all diagnoses in this split
            split_payload["service_lines"] = [_make_overflow_service_line(len(chunk))]

        payloads.append((split_payload, []))

    return payloads


def _split_diagnoses(diagnoses: list[dict]) -> list[list[dict]]:
    """Paginate a flat diagnosis list into chunks of MAX_DIAGNOSES_PER_ENCOUNTER."""
    chunks = []
    for i in range(0, len(diagnoses), MAX_DIAGNOSES_PER_ENCOUNTER):
        chunks.append(diagnoses[i : i + MAX_DIAGNOSES_PER_ENCOUNTER])
    return chunks


def _format_diagnosis_chunk(chunk: list[dict]) -> list[dict]:
    """Re-format a chunk so the first diagnosis is ABK (primary) and the rest are ABF."""
    if not chunk:
        return []
    formatted = [{"code": chunk[0]["code"], "code_type": "ABK"}]
    formatted.extend({"code": d["code"], "code_type": "ABF"} for d in chunk[1:])
    return formatted


def _clamp_service_line_pointers(
    service_lines: list[dict], max_index: int
) -> list[dict]:
    """Drop diagnosis pointers that exceed ``max_index``.

    Those diagnoses are on a supplemental split. No remapping is needed
    because diagnoses are kept in their original rank order.
    """
    clamped = []
    for line in service_lines:
        new_line = dict(line)
        old_pointers = line.get("diagnosis_pointers", [])
        new_pointers = [p for p in old_pointers if p <= max_index]
        if new_pointers:
            new_line["diagnosis_pointers"] = new_pointers
        else:
            new_line.pop("diagnosis_pointers", None)
        clamped.append(new_line)
    return clamped


def _make_overflow_service_line(num_diagnoses: int) -> dict:
    """Build a 99499 placeholder service line for a supplemental split."""
    return {
        "procedure_code": OVERFLOW_CPT_CODE,
        "units": "UN",
        "quantity": "1",
        "charge_amount_cents": OVERFLOW_CHARGE_CENTS,
        "diagnosis_pointers": list(
            range(min(num_diagnoses, MAX_DIAGNOSIS_POINTERS_PER_SERVICE_LINE))
        ),
    }


def _add_core_fields(
    claim: Claim, payload: dict, errors: list[str], tz: ZoneInfo = DEFAULT_TZ
) -> None:
    coverages = active_coverages_ordered(claim)
    payload["responsible_party"] = "INSURANCE_PAY" if coverages else "SELF_PAY"

    if claim.id:
        payload["external_id"] = f"canvas:{claim.id}"
    else:
        errors.append("External encounter id is missing")

    dos = _date_of_service(claim, tz)
    if dos:
        payload["date_of_service"] = str(dos)
    else:
        errors.append("Date of service is missing")

    payload["provider_accepts_assignment"] = (
        True if claim.accept_assign is None else claim.accept_assign
    )

    place_of_service = _place_of_service(claim)
    if place_of_service:
        payload["place_of_service_code"] = place_of_service
    else:
        errors.append("Place of service is missing")

    prior_auth = getattr(claim, "prior_auth", None)
    if prior_auth:
        payload["prior_authorization_number"] = str(prior_auth)


def _add_diagnoses(claim: Claim, payload: dict, errors: list[str]) -> None:
    diagnosis_codes = list(
        claim.diagnosis_codes.order_by("rank").values_list("code", flat=True)
    )
    if not diagnosis_codes:
        errors.append("Diagnosis code is missing")
        return

    # First code is ABK (primary ICD-10), rest are ABF
    formatted = [{"code": diagnosis_codes[0], "code_type": "ABK"}]
    formatted.extend({"code": code, "code_type": "ABF"} for code in diagnosis_codes[1:])
    payload["diagnoses"] = formatted


def _add_service_lines(claim: Claim, payload: dict) -> None:
    lines = []
    diagnosis_code_to_index = {
        d["code"]: i for i, d in enumerate(payload.get("diagnoses", []))
    }

    for line_item in claim.get_active_claim_line_items():
        service_line: dict[str, Any] = {
            "procedure_code": line_item.proc_code,
            "units": "UN",
            "external_id": str(line_item.id),
        }
        if line_item.units is not None:
            service_line["quantity"] = str(line_item.units)

        if line_item.charge is not None:
            service_line["charge_amount_cents"] = str(int(line_item.charge * 100))

        pointer_indices = []
        for linked_dx in line_item.diagnosis_codes.filter(linked=True):
            code = getattr(linked_dx.claim_diagnosis_code, "code", None)
            if code is not None and code in diagnosis_code_to_index:
                pointer_indices.append(diagnosis_code_to_index[code])
        if pointer_indices:
            service_line["diagnosis_pointers"] = sorted(pointer_indices)[
                :MAX_DIAGNOSIS_POINTERS_PER_SERVICE_LINE
            ]

        modifiers = list(line_item.modifiers.values_list("modifier", flat=True))
        if modifiers:
            service_line["modifiers"] = modifiers

        lines.append(service_line)

    if lines:
        payload["service_lines"] = lines


def _add_patient(claim: Claim, payload: dict, errors: list[str]) -> None:
    claim_patient = getattr(claim, "patient", None)
    if not claim_patient:
        errors.append("Claim patient info is missing")
        return

    required = {
        "first_name": claim_patient.first_name,
        "last_name": claim_patient.last_name,
        "date_of_birth": str(claim_patient.dob) if claim_patient.dob else None,
        "address1": claim_patient.addr1,
        "city": claim_patient.city,
        "state": claim_patient.state,
        "zip": claim_patient.zip,
    }
    missing = [k for k, v in required.items() if not v]
    if missing or claim_patient.sex is None:
        errors.append(
            f"The following items were missing for the patient: {', '.join(missing)}"
        )
        return

    note = claim.note
    external_patient_id = (
        str(note.patient.id) if note and note.patient else str(claim_patient.id)
    )

    patient_payload: dict[str, Any] = {
        "external_id": f"canvas:{external_patient_id}",
        "first_name": claim_patient.first_name,
        "last_name": claim_patient.last_name,
        "date_of_birth": str(claim_patient.dob),
        "gender": _gender(claim_patient.sex),
        "address": {
            "address1": claim_patient.addr1,
            "city": claim_patient.city,
            "state": claim_patient.state,
            "zip_code": _split_zip(claim_patient.zip)[0],
        },
    }
    if claim_patient.addr2:
        patient_payload["address"]["address2"] = claim_patient.addr2

    payload["patient"] = patient_payload


def _add_billing_provider(claim: Claim, payload: dict, errors: list[str]) -> None:
    provider = claim.provider
    if not provider:
        errors.append("Claim provider info is missing")
        return

    zip_code, zip_plus_four = _split_zip(provider.billing_provider_zip)
    required = {
        "billing_provider_npi": provider.billing_provider_npi,
        "billing_provider_tax_id": provider.billing_provider_tax_id,
        "billing_provider_address_1": provider.billing_provider_addr1,
        "billing_provider_state": provider.billing_provider_state,
        "billing_provider_city": provider.billing_provider_city,
        "billing_provider_zip_code": zip_code,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        errors.append(
            f"The following items were missing for the billing provider: {', '.join(missing)}"
        )
        return

    billing_provider: dict[str, Any] = {
        "npi": provider.billing_provider_npi,
        "tax_id": provider.billing_provider_tax_id,
        "address": {
            "address1": provider.billing_provider_addr1,
            "city": provider.billing_provider_city,
            "state": provider.billing_provider_state,
            "zip_code": zip_code,
            "zip_plus_four_code": zip_plus_four,
        },
    }
    if provider.billing_provider_addr2:
        billing_provider["address"]["address2"] = provider.billing_provider_addr2
    if provider.billing_provider_name:
        billing_provider["organization_name"] = provider.billing_provider_name
    if provider.billing_provider_taxonomy:
        billing_provider["taxonomy_code"] = provider.billing_provider_taxonomy

    payload["billing_provider"] = billing_provider


def _add_rendering_provider(claim: Claim, payload: dict, errors: list[str]) -> None:
    provider = claim.provider
    if not provider:
        return

    # NPI OR first+last name required
    has_npi = bool(provider.provider_npi and provider.provider_npi != "0")
    has_name = bool(provider.provider_first_name and provider.provider_last_name)
    if not (has_npi or has_name):
        errors.append("Rendering provider: NPI OR first+last name is required")
        return

    rendering: dict[str, Any] = {}
    if has_npi:
        rendering["npi"] = provider.provider_npi
    if provider.provider_first_name:
        rendering["first_name"] = provider.provider_first_name
    if provider.provider_last_name:
        rendering["last_name"] = provider.provider_last_name
    if provider.provider_taxonomy:
        rendering["taxonomy_code"] = provider.provider_taxonomy

    # Address is optional but must be complete if any part is provided
    zip_code, zip_plus_four = _split_zip(provider.provider_zip)
    address_required = {
        "address1": provider.provider_addr1,
        "city": provider.provider_city,
        "state": provider.provider_state,
        "zip_code": zip_code,
    }
    if all(address_required.values()):
        rendering["address"] = {
            **address_required,
            "zip_plus_four_code": zip_plus_four,
        }
        if provider.provider_addr2:
            rendering["address"]["address2"] = provider.provider_addr2

    payload["rendering_provider"] = rendering


def _add_service_facility(claim: Claim, payload: dict, errors: list[str]) -> None:
    provider = claim.provider
    if not provider:
        return

    zip_code, zip_plus_four = _split_zip(provider.facility_zip)
    required = {
        "service_facility_org_name": provider.facility_name,
        "service_facility_address_1": provider.facility_addr1,
        "service_facility_state": provider.facility_state,
        "service_facility_city": provider.facility_city,
        "service_facility_zip_code": zip_code,
    }
    missing = [k for k, v in required.items() if not v]

    if not missing:
        facility: dict[str, Any] = {
            "organization_name": provider.facility_name,
            "address": {
                "address1": provider.facility_addr1,
                "city": provider.facility_city,
                "state": provider.facility_state,
                "zip_code": zip_code,
                "zip_plus_four_code": zip_plus_four,
            },
        }
        if provider.facility_addr2:
            facility["address"]["address2"] = provider.facility_addr2
        payload["service_facility"] = facility
        return

    # Facility is required for telehealth claims
    if payload.get("place_of_service_code") in TELEHEALTH_PLACES_OF_SERVICE:
        errors.append(
            f"Service facility information is required for telehealth claims, "
            f"but was missing: {', '.join(missing)}"
        )


def _add_subscribers(claim: Claim, payload: dict, errors: list[str]) -> None:
    coverages_ordered = active_coverages_ordered(claim)

    for index, coverage in enumerate(coverages_ordered[:2]):
        key = "subscriber_primary" if index == 0 else "subscriber_secondary"
        subscriber_payload = _subscriber_payload(coverage)
        if subscriber_payload:
            payload[key] = subscriber_payload
        elif (
            key == "subscriber_primary"
            and payload.get("responsible_party") == "INSURANCE_PAY"
        ):
            errors.append(
                "Because the responsible_party is INSURANCE_PAY, the primary subscriber "
                "is required but has missing fields"
            )


def _subscriber_payload(coverage: ClaimCoverage) -> dict | None:
    """Build a subscriber dict from a ClaimCoverage, or None if required fields are missing."""
    required = [
        coverage.subscriber_first_name,
        coverage.subscriber_last_name,
        coverage.subscriber_sex,
        coverage.patient_relationship_to_subscriber,
        coverage.subscriber_number,
        coverage.payer_id,
        coverage.payer_name,
    ]
    if not all(required):
        return None

    subscriber: dict[str, Any] = {
        "first_name": coverage.subscriber_first_name,
        "last_name": coverage.subscriber_last_name,
        "gender": _gender(coverage.subscriber_sex),
        "patient_relationship_to_subscriber_code": coverage.patient_relationship_to_subscriber,
        "insurance_card": {
            "member_id": coverage.subscriber_number,
            "payer_id": coverage.payer_id,
            "payer_name": coverage.payer_name,
            "emr_payer_crosswalk": CANVAS,
        },
    }

    if coverage.subscriber_dob:
        subscriber["date_of_birth"] = str(coverage.subscriber_dob)
    if coverage.subscriber_group:
        subscriber["insurance_card"]["group_number"] = coverage.subscriber_group
    plan_name = getattr(coverage.coverage, "plan", None) if coverage.coverage else None
    if plan_name:
        subscriber["insurance_card"]["plan_name"] = plan_name

    if (
        coverage.subscriber_addr1
        and coverage.subscriber_city
        and coverage.subscriber_state
        and coverage.subscriber_zip
    ):
        subscriber["address"] = {
            "address1": coverage.subscriber_addr1,
            "city": coverage.subscriber_city,
            "state": coverage.subscriber_state,
            "zip_code": _split_zip(coverage.subscriber_zip)[0],
        }
        if coverage.subscriber_addr2:
            subscriber["address"]["address2"] = coverage.subscriber_addr2

    return subscriber


def _date_of_service(claim: Claim, tz: ZoneInfo = DEFAULT_TZ) -> Any:
    """Determine the date of service for the claim.

    Converts the note's datetime_of_service to the instance's configured
    time zone before extracting the date. Falls back to the first line
    item's from_date if the note has no datetime.
    """
    note = claim.note
    if note and getattr(note, "datetime_of_service", None):
        return note.datetime_of_service.astimezone(tz).date()

    first_line = claim.line_items.first()
    if first_line and first_line.from_date:
        return first_line.from_date
    return None


def _place_of_service(claim: Claim) -> str | None:
    first_line = claim.line_items.first()
    if first_line and first_line.place_of_service:
        return first_line.place_of_service
    return None
