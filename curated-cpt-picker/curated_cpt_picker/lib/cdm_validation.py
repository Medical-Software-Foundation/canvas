"""Shared validation that checks a CPT code against the ChargeDescriptionMaster.

Used in two places:
  1. Admin save (`admin_api`) — validates one CPT before persisting a curated entry.
  2. Picker open (`picker_api`) — bulk-filters curated entries before showing them.
"""

from dataclasses import dataclass
from datetime import date

from canvas_sdk.v1.data import ChargeDescriptionMaster


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating one CPT code against the CDM."""

    is_valid: bool
    reason: str | None = None  # populated on failure; suitable for user-facing 422 body


def _is_currently_active(cdm_row: ChargeDescriptionMaster, today: date) -> bool:
    """Return True if this CDM row is active today.

    Rules:
      - effective_date is required. A null effective_date means the CDM row
        was never properly configured and is treated as invalid.
      - end_date null means open-ended (no expiration).
      - Both date bounds are inclusive of today.
    """
    if cdm_row.effective_date is None or cdm_row.effective_date > today:
        return False
    if cdm_row.end_date is not None and cdm_row.end_date < today:
        return False
    return True


def validate_cpt_code(cpt_code: str, today: date | None = None) -> ValidationResult:
    """Validate a single CPT code against the CDM.

    Returns a ValidationResult with a human-readable `reason` on failure
    that callers can surface in 422 responses or admin UI errors.
    """
    if today is None:
        today = date.today()

    cdm_rows = list(ChargeDescriptionMaster.objects.filter(cpt_code=cpt_code))

    if not cdm_rows:
        return ValidationResult(
            is_valid=False,
            reason=f"CPT code '{cpt_code}' is not in the ChargeDescriptionMaster.",
        )

    if any(_is_currently_active(row, today) for row in cdm_rows):
        return ValidationResult(is_valid=True)

    return ValidationResult(
        is_valid=False,
        reason=f"CPT code '{cpt_code}' is in the ChargeDescriptionMaster but not currently active (check effective_date / end_date).",
    )


def filter_valid_cpt_codes(cpt_codes: list[str], today: date | None = None) -> set[str]:
    """Return the subset of cpt_codes that have at least one currently-active CDM row.

    Used by the picker to bulk-filter curated entries in a single round-trip
    to the database instead of one query per code.
    """
    if today is None:
        today = date.today()

    if not cpt_codes:
        return set()

    cdm_rows = ChargeDescriptionMaster.objects.filter(cpt_code__in=cpt_codes)
    return {row.cpt_code for row in cdm_rows if _is_currently_active(row, today)}
