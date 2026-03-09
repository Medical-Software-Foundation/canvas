from canvas_sdk.effects import Effect
from canvas_sdk.effects.claim import ClaimEffect
from canvas_sdk.v1.data import Claim
from canvas_sdk.v1.data.claim import ClaimQueues

from auto_submit_clean_claims.helpers.fhir_client import FhirClient
from auto_submit_clean_claims.helpers.scrub_checks import (
    check_clia,
    check_coverage,
    check_diagnoses,
    check_hospital_dates,
    check_line_items,
    check_patient,
    check_provider,
)
from logger import log

STATIC_LABELS = {
    "Missing Billing Provider Tax ID",
    "Incorrect Billing Provider Tax ID (must be 9 chars)",
    "Missing Rendering Provider Tax ID",
    "Incorrect Rendering Provider Tax ID (must be 9 chars)",
    "Missing Billing Provider Group NPI",
    "Incorrect Billing Provider Group NPI (must be 10 chars)",
    "Missing Rendering Provider NPI",
    "Incorrect Rendering Provider NPI (must be 10 chars)",
    "Lab charges with QW modifier but missing CLIA#",
    "Hospital inpatient charges require admit/discharge dates",
    "Patient address incomplete",
    "Patient DOB missing",
    "Workers Comp/Auto claim missing patient SSN",
    "Missing coverage policy ID",
    "Missing subscriber address for non-self subscriber",
    "Coverage is not active for this date of service",
    "No service charges on claim",
    "Total billed amount is $0",
    "No diagnosis codes",
    "Duplicate diagnosis codes",
}

DYNAMIC_LABEL_PREFIXES = (
    "Charge ",
    "Primary diagnosis ",
)


def is_plugin_label(label_name: str) -> bool:
    """Check if a label was created by this plugin."""
    if label_name in STATIC_LABELS:
        return True
    return any(label_name.startswith(prefix) for prefix in DYNAMIC_LABEL_PREFIXES)


def scrub(claim: Claim, fhir_client: FhirClient) -> list[str]:
    """Run all scrub checks against a claim. Returns error descriptions. Empty = clean."""
    errors: list[str] = []
    provider = claim.provider
    active_lines = claim.line_items.active()
    coverage = claim.coverages.filter(active=True).first()

    errors.extend(check_provider(provider))
    errors.extend(check_clia(fhir_client, claim, provider, active_lines))
    errors.extend(check_hospital_dates(provider, active_lines))
    errors.extend(check_patient(claim))
    if coverage:
        errors.extend(check_coverage(claim, coverage))
    errors.extend(check_line_items(claim, active_lines))
    errors.extend(check_diagnoses(claim, active_lines))

    return errors


def process_claim(claim: Claim, fhir_client: FhirClient) -> list[Effect]:
    """Scrub a claim, manage labels, and move to submission if clean."""
    errors = scrub(claim, fhir_client)
    claim_id = str(claim.id)
    effects: list[Effect] = []

    existing_labels = [l.name for l in claim.labels.all()]
    stale_labels = [
        name for name in existing_labels
        if is_plugin_label(name) and name not in errors
    ]
    if stale_labels:
        effects.append(ClaimEffect(claim_id=claim_id).remove_labels(stale_labels))

    if errors:
        new_labels = [e for e in errors if e not in existing_labels]
        if new_labels:
            effects.append(ClaimEffect(claim_id=claim_id).add_labels(new_labels))
        log.info(
            f"Claim {claim_id} has {len(errors)} error(s), staying in Coding queue: "
            f"{'; '.join(errors)}"
        )
        return effects

    log.info(f"Claim {claim_id} is clean — moving to Submission queue")
    effects.append(
        ClaimEffect(claim_id=claim_id).move_to_queue(ClaimQueues.QUEUED_FOR_SUBMISSION.label)
    )
    return effects
