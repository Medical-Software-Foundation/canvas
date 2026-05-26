"""Shared validation that checks a CPT code against the ChargeDescriptionMaster.

Used in two places:
  1. Admin save (`admin_api`) — validates one CPT before persisting a curated entry.
  2. Picker open (`picker_api`) — bulk-filters curated entries before showing them.
"""

from dataclasses import dataclass
from datetime import date

from canvas_sdk.v1.data import ChargeDescriptionMaster


# Canvas's BillingLineItem.description is varchar(255). When AddBillingLineItem
# fires, Canvas's effect interpreter copies the CDM row's name/short_name into
# that column without truncating, so any CDM row whose name or short_name
# exceeds this limit will make AddBillingLineItem fail with
# `DataError: value too long for type character varying(255)`.
# We reject these codes at admin save and silently skip them at picker render.
BILLING_DESCRIPTION_MAX_LEN = 255


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


def _description_fits(cdm_row: ChargeDescriptionMaster) -> bool:
    """Return True if this row's name and short_name fit Canvas's
    BillingLineItem.description column (varchar(255)).

    Canvas's effect interpreter copies CDM text into the 255-char description
    column without truncation; this guard prevents the silent
    `value too long` failure when AddBillingLineItem fires.
    """
    name_len = len(cdm_row.name or "")
    short_len = len(cdm_row.short_name or "")
    return name_len <= BILLING_DESCRIPTION_MAX_LEN and short_len <= BILLING_DESCRIPTION_MAX_LEN


def _is_usable(cdm_row: ChargeDescriptionMaster, today: date) -> bool:
    """A CDM row is usable for billing today if it is currently active AND its
    description fields fit the BillingLineItem column."""
    return _is_currently_active(cdm_row, today) and _description_fits(cdm_row)


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

    active_rows = [row for row in cdm_rows if _is_currently_active(row, today)]
    if not active_rows:
        return ValidationResult(
            is_valid=False,
            reason=f"CPT code '{cpt_code}' is in the ChargeDescriptionMaster but not currently active (check effective_date / end_date).",
        )

    if not any(_description_fits(row) for row in active_rows):
        max_name = max(len(row.name or "") for row in active_rows)
        max_short = max(len(row.short_name or "") for row in active_rows)
        return ValidationResult(
            is_valid=False,
            reason=(
                f"CPT code '{cpt_code}' has a description that is too long "
                f"for Canvas's billing line item (name: {max_name} chars, "
                f"short_name: {max_short} chars; both must be ≤ {BILLING_DESCRIPTION_MAX_LEN}). "
                f"Shorten this code's short_name in Settings → Charge Description Master, "
                f"then try again."
            ),
        )

    return ValidationResult(is_valid=True)


def filter_valid_cpt_codes(cpt_codes: list[str], today: date | None = None) -> set[str]:
    """Return the subset of cpt_codes that have at least one currently-usable CDM row.

    Used by the picker to bulk-filter curated entries in a single round-trip
    to the database. "Usable" means active today AND with name/short_name that
    fit Canvas's BillingLineItem description column.
    """
    if today is None:
        today = date.today()

    if not cpt_codes:
        return set()

    cdm_rows = ChargeDescriptionMaster.objects.filter(cpt_code__in=cpt_codes)
    return {row.cpt_code for row in cdm_rows if _is_usable(row, today)}
