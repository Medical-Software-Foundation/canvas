"""Patient and reviewer matching from extracted document data."""

from canvas_sdk.v1.data import Patient, Staff
from logger import log

from doc_intake_ai.models import DocumentExtraction, PatientMatch, ReviewerMatch


def find_patient(extraction: DocumentExtraction) -> PatientMatch:
    """Find patient by MRN, then name+DOB, then name only.

    Returns PatientMatch with patient if exactly one match found.
    Skips if multiple matches (ambiguous).
    """
    if extraction.patient_id:
        patients = list(Patient.objects.filter(mrn=extraction.patient_id))
        if len(patients) == 1:
            log.info("[MATCH] Patient matched by MRN")
            return PatientMatch(patient=patients[0])
        if len(patients) > 1:
            return PatientMatch(error="Multiple patients match MRN")

    first, last = _parse_name(
        extraction.patient_first_name,
        extraction.patient_last_name,
        extraction.patient_name,
    )
    if not first or not last:
        return PatientMatch()

    if extraction.date_of_birth:
        patients = list(Patient.objects.filter(
            first_name__iexact=first,
            last_name__iexact=last,
            birth_date=extraction.date_of_birth,
        ))
        if len(patients) == 1:
            log.info("[MATCH] Patient matched by name + DOB")
            return PatientMatch(patient=patients[0])
        if len(patients) > 1:
            return PatientMatch(error="Multiple patients match name + DOB")

    patients = list(Patient.objects.filter(
        first_name__iexact=first,
        last_name__iexact=last,
    ))
    if len(patients) == 1:
        log.info("[MATCH] Patient matched by name")
        return PatientMatch(patient=patients[0])
    if len(patients) > 1:
        return PatientMatch(error="Multiple patients match name")

    return PatientMatch()


def find_reviewer(
    extraction: DocumentExtraction,
    default_reviewer: str | None = None,
) -> ReviewerMatch:
    """Find reviewer by NPI, then name. Falls back to DEFAULT_REVIEWER secret.

    The default_reviewer secret accepts an NPI number (e.g. "1234567890")
    or a staff name (e.g. "Jane Smith") — whichever the admin knows.

    Returns ReviewerMatch with auto_assigned=True for fallback assignments.
    """
    if extraction.practitioner_npi:
        staff = list(Staff.objects.filter(npi_number=extraction.practitioner_npi))
        if len(staff) == 1:
            log.info("[MATCH] Reviewer matched by NPI")
            return ReviewerMatch(reviewer=staff[0])

    first, last = _parse_name(
        extraction.practitioner_first_name,
        extraction.practitioner_last_name,
        extraction.practitioner_name,
    )
    if first and last:
        staff = list(Staff.objects.filter(
            first_name__iexact=first,
            last_name__iexact=last,
        ))
        if len(staff) == 1:
            log.info("[MATCH] Reviewer matched by name")
            return ReviewerMatch(reviewer=staff[0])

    if default_reviewer:
        resolved = _resolve_default_reviewer(default_reviewer)
        if resolved:
            log.info("[MATCH] Reviewer assigned from DEFAULT_REVIEWER")
            return ReviewerMatch(reviewer=resolved, auto_assigned=True)

    bot = Staff.objects.filter(first_name__iexact="Canvas", last_name__iexact="Bot").first()
    default = bot or Staff.objects.first()
    if default:
        log.info("[MATCH] Reviewer auto-assigned")
        return ReviewerMatch(reviewer=default, auto_assigned=True)

    return ReviewerMatch()


def _resolve_default_reviewer(value: str) -> Staff | None:
    """Resolve DEFAULT_REVIEWER secret to a Staff member.

    Accepts NPI (e.g. "1234567890") or name (e.g. "Jane Smith").
    Tries NPI first, then name lookup.
    """
    value = value.strip()
    if not value:
        return None

    # Try as NPI (all digits, 10 chars)
    if value.isdigit():
        match = Staff.objects.filter(npi_number=value).first()
        if match:
            return match

    # Try as "First Last" name
    first, last = _parse_name(None, None, value)
    if first and last:
        staff = list(Staff.objects.filter(
            first_name__iexact=first,
            last_name__iexact=last,
        ))
        if len(staff) == 1:
            return staff[0]
        if len(staff) > 1:
            log.warning("[MATCH] DEFAULT_REVIEWER '%s' matches multiple staff", value)

    log.warning("[MATCH] Could not resolve DEFAULT_REVIEWER '%s'", value)
    return None


def _parse_name(
    first: str | None,
    last: str | None,
    full_name: str | None,
) -> tuple[str | None, str | None]:
    """Parse first and last name from split fields or combined full name."""
    if first and last:
        return first, last

    if full_name:
        parts = full_name.strip().split()
        if len(parts) >= 2:
            return first or parts[0], last or parts[-1]
        if len(parts) == 1:
            return first or parts[0], last

    return first, last
