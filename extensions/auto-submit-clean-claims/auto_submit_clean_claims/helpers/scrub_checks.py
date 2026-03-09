from canvas_sdk.v1.data import ClaimLineItemDiagnosisCode
from canvas_sdk.v1.data.coverage import CoverageRelationshipCode, CoverageStack


def check_provider(provider) -> list[str]:
    """Validate billing and rendering provider tax IDs (9 chars) and NPIs (10 chars)."""
    errors: list[str] = []

    if not provider.billing_provider_tax_id:
        errors.append("Missing Billing Provider Tax ID")
    elif len(provider.billing_provider_tax_id) != 9:
        errors.append("Incorrect Billing Provider Tax ID (must be 9 chars)")

    if not provider.provider_tax_id:
        errors.append("Missing Rendering Provider Tax ID")
    elif len(provider.provider_tax_id) != 9:
        errors.append("Incorrect Rendering Provider Tax ID (must be 9 chars)")

    if not provider.billing_provider_npi:
        errors.append("Missing Billing Provider Group NPI")
    elif len(provider.billing_provider_npi) != 10:
        errors.append("Incorrect Billing Provider Group NPI (must be 10 chars)")

    if not provider.provider_npi:
        errors.append("Missing Rendering Provider NPI")
    elif len(provider.provider_npi) != 10:
        errors.append("Incorrect Rendering Provider NPI (must be 10 chars)")

    return errors


def check_hospital_dates(provider, active_lines) -> list[str]:
    """Check that inpatient (POS 21) charges have admit/discharge dates set."""
    hospital_charges = [li for li in active_lines if li.place_of_service == "21"]
    if hospital_charges and provider.hosp_from_date == "0000-00-00":
        return ["Hospital inpatient charges require admit/discharge dates"]
    return []


def check_patient(claim) -> list[str]:
    """Validate patient address, DOB, and SSN (required for workers comp/auto claims)."""
    errors: list[str] = []
    patient = claim.patient

    if not all([patient.addr1, patient.city, patient.state, patient.zip]):
        errors.append("Patient address incomplete")

    if patient.dob == "0000-00-00":
        errors.append("Patient DOB missing")

    if (claim.auto_accident or claim.employment_related) and not patient.ssn:
        errors.append("Workers Comp/Auto claim missing patient SSN")

    return errors


def check_coverage(claim, coverage) -> list[str]:
    """Validate coverage policy ID, subscriber address, and that coverage is active for the DOS."""
    errors: list[str] = []

    if not coverage.subscriber_number:
        errors.append("Missing coverage policy ID")

    if coverage.patient_relationship_to_subscriber != CoverageRelationshipCode.SELF and not all([
        coverage.subscriber_addr1,
        coverage.subscriber_city,
        coverage.subscriber_state,
        coverage.subscriber_zip,
    ]):
        errors.append("Missing subscriber address for non-self subscriber")

    source_coverage = coverage.coverage
    dos = claim.note.datetime_of_service.date()
    start = source_coverage.coverage_start_date
    end = source_coverage.coverage_end_date
    in_range = (start <= dos) and (not end or dos <= end)

    if not in_range or source_coverage.stack != CoverageStack.IN_USE:
        errors.append("Coverage is not active for this date of service")

    return errors


def check_line_items(claim, active_lines) -> list[str]:
    """Check for at least one charge, non-zero total, valid units, and complete NDC data."""
    errors: list[str] = []

    if not active_lines.exists():
        errors.append("No service charges on claim")

    if active_lines.exists() and claim.total_charges == 0:
        errors.append("Total billed amount is $0")

    for li in active_lines:
        if li.units < 1:
            errors.append(f"Charge {li.proc_code} has units < 1")

    for li in active_lines:
        if li.ndc_code and (not li.ndc_measure or not li.ndc_dosage):
            errors.append(f"Charge {li.proc_code} has NDC code but missing dosage/measure")

    return errors


def check_diagnoses(claim, active_lines) -> list[str]:
    """Validate diagnosis codes exist, are linked to charges, have no duplicates, and primary is not an external cause."""
    errors: list[str] = []

    if not claim.diagnosis_codes.exists():
        errors.append("No diagnosis codes")
        return errors

    for li in active_lines:
        has_linked = ClaimLineItemDiagnosisCode.objects.filter(
            line_item=li, linked=True
        ).exists()
        if not has_linked:
            errors.append(f"Charge {li.proc_code} missing diagnosis pointer")

    dx_codes = list(claim.diagnosis_codes.values_list("code", flat=True))
    if len(dx_codes) != len(set(dx_codes)):
        errors.append("Duplicate diagnosis codes")

    primary_dx = claim.diagnosis_codes.order_by("rank").first()
    if primary_dx and primary_dx.rank == 1 and primary_dx.code[0] in ("V", "W", "X", "Y"):
        errors.append(f"Primary diagnosis {primary_dx.code} is an external cause code")

    return errors


def check_clia(fhir_client, claim, provider, active_lines) -> list[str]:
    """Check if lab charges with QW modifier are missing a CLIA number.
    Uses FHIR Claim read to get line item modifiers (not available in SDK)."""
    if provider.clia_number:
        return []

    lab_charges = [li for li in active_lines if li.proc_code.startswith("8")]
    if not lab_charges:
        return []

    fhir_claim = fhir_client.read("Claim", str(claim.id))
    for item in fhir_claim.get("item", []):
        proc_code = item.get("productOrService", {}).get("coding", [{}])[0].get("code", "")
        if not proc_code.startswith("8"):
            continue
        modifiers = [
            m.get("coding", [{}])[0].get("code", "")
            for m in item.get("modifier", [])
        ]
        if "QW" in modifiers:
            return ["Lab charges with QW modifier but missing CLIA#"]

    return []
