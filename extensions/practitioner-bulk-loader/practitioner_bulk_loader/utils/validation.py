"""
Validation rules for practitioner CSV records.

These rules are the server-side source of truth. Client-side JavaScript
mirrors them for fast feedback before the server round-trip.

All validators operate on the *merged* practitioner record produced by
the CSV parser, not on raw CSV rows.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# License-type canonical values are the all-caps codes Canvas's
# /Practitioner endpoint accepts on `qualification.code.text`. Empirically
# verified against a real Canvas instance: CLIA / DEA / PTAN / STATE / TAXONOMY
# round-trip correctly. OTHER and SPI are accepted by the request but
# Canvas falls back to storing the qualification with `code.text="License"`
# (a Canvas-side quirk — the docs list OTHER as supported but the API does
# not honor it). README has a note about this.
VALID_LICENSE_TYPES = {"CLIA", "DEA", "PTAN", "STATE", "TAXONOMY", "SPI", "OTHER"}

# Map common user-friendly aliases to the canonical form. CSV inputs from
# customers often arrive as "State license", "Taxonomy", etc.; we accept
# those (case-insensitively) and normalise to the all-caps form Canvas
# wants. Canonical-form spellings round-trip unchanged.
_LICENSE_TYPE_ALIASES: dict[str, str] = {}
for canonical in VALID_LICENSE_TYPES:
    _LICENSE_TYPE_ALIASES[canonical.lower()] = canonical
_LICENSE_TYPE_ALIASES["state license"] = "STATE"

# Pre-computed lowercase set for case-insensitive matching.
_VALID_LICENSE_TYPES_LOWER = set(_LICENSE_TYPE_ALIASES.keys())

VALID_STATE_CODES = {
    # 50 states
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    # District of Columbia
    "DC",
    # US territories
    "AS", "GU", "MP", "PR", "VI",
    # Freely associated states
    "FM", "MH", "PW",
}

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_DIGITS_ONLY_RE = re.compile(r"^\d+$")

# Dates: accept MM-DD-YYYY and MM/DD/YYYY (the format real-world spreadsheets
# produce — e.g. 01-08-1973, 1/1/2023), plus ISO YYYY-MM-DD for tolerance.
# Month/day may be padded or unpadded. All values are normalised to ISO at
# the FHIR boundary via `to_fhir_date()`.
_DATE_RE_MDY = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_DATE_RE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")

_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_NPI_RE = re.compile(r"^\d{10}$")


def canonicalize_license_type(raw: str) -> str:
    """Return the canonical (all-caps) form of a license type string.

    Accepts both the canonical form ("STATE") and common user-friendly
    aliases ("State license", "state license") and maps them all to the
    canonical value Canvas's API expects. Falls back to returning the raw
    value if nothing matches — validation has already caught that case.
    """
    return _LICENSE_TYPE_ALIASES.get(raw.lower(), raw)


class ValidationError:
    """A hard error that blocks import for a practitioner row."""

    def __init__(self, row: int, field: str, value: str, message: str) -> None:
        self.row = row
        self.field = field
        self.value = value
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "field": self.field,
            "value": self.value,
            "message": self.message,
        }


class ValidationWarning:
    """A soft warning displayed to the user but not blocking import.

    Warnings do not carry a ``value`` field — they describe aggregate
    conditions (e.g. "no license is primary") rather than a single
    offending cell value.  If a trivial value is available it is already
    embedded in the message text (see Rule 13 and Rule 14).
    """

    def __init__(self, row: int, message: str) -> None:
        self.row = row
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "message": self.message}


def _parse_date_parts(value: str) -> tuple[int, int, int] | None:
    """Parse MM-DD-YYYY / MM/DD/YYYY / YYYY-MM-DD → (year, month, day), or None."""
    m = _DATE_RE_MDY.match(value)
    if m:
        month, day, year = m.groups()
        return int(year), int(month), int(day)
    m = _DATE_RE_ISO.match(value)
    if m:
        year, month, day = m.groups()
        return int(year), int(month), int(day)
    return None


def _is_valid_date(value: str) -> bool:
    """Return True if value parses to a real calendar date in an accepted format.

    Accepted: MM-DD-YYYY, MM/DD/YYYY (preferred), or ISO YYYY-MM-DD.
    """
    parts = _parse_date_parts(value)
    if parts is None:
        return False
    try:
        date(*parts)
        return True
    except ValueError:
        return False


def to_fhir_date(value: str) -> str:
    """Normalise an accepted date string to ISO YYYY-MM-DD for FHIR.

    Passes the input through unchanged if it doesn't match a known pattern —
    validation elsewhere will have already flagged it as invalid. Blank input
    returns blank.
    """
    if not value:
        return ""
    parts = _parse_date_parts(value)
    if parts is None:
        return value
    year, month, day = parts
    return f"{year:04d}-{month:02d}-{day:02d}"


def validate_practitioner(
    row_number: int,
    practitioner: dict[str, Any],
) -> tuple[list[ValidationError], list[ValidationWarning]]:
    """
    Run all validation rules against a merged practitioner record.

    row_number - 1-based row in the original CSV for error reporting
                 (callers should pass the index of the first row for this email).

    Role codes are not checked here — Canvas validates them authoritatively at
    POST /Practitioner time and returns a 422 OperationOutcome if the code is
    not configured. Surfacing role errors in the results UI (where Canvas's
    message lives) avoids the false-positive problem of pre-flight checks
    against the StaffRole assignment table (which doesn't expose unassigned-
    but-configured roles).

    Returns (errors, warnings) — both are empty lists on success.
    """
    errors: list[ValidationError] = []
    warnings: list[ValidationWarning] = []

    def err(field: str, value: str, message: str) -> None:
        errors.append(ValidationError(row_number, field, value, message))

    def warn(message: str) -> None:
        warnings.append(ValidationWarning(row_number, message))

    # Rule 1: Required fields non-empty
    for field in (
        "first_name",
        "last_name",
        "role",
        "email",
        "phone",
        "dob",
        "primary_practice_location",
    ):
        raw_val = practitioner.get(field, "")
        if not raw_val.strip():
            human = field.replace("_", " ").title()
            err(human, raw_val, f"{human} is required.")

    # Rule 2: Email format
    email = practitioner.get("email", "").strip()
    if email and not _EMAIL_RE.match(email):
        err("Email", email, "Email address format is invalid.")

    # Rule 3: Phone digits-only
    phone = practitioner.get("phone", "").strip()
    if phone and not _DIGITS_ONLY_RE.match(phone):
        err("Phone", phone, "Phone must contain digits only (no spaces or special characters).")

    # Rule 4: Fax digits-only (if present)
    fax = practitioner.get("fax", "").strip()
    if fax and not _DIGITS_ONLY_RE.match(fax):
        err("Fax", fax, "Fax must contain digits only.")

    # Rule 5: NPI exactly 10 digits (if present)
    npi = practitioner.get("npi", "").strip()
    if npi and not _NPI_RE.match(npi):
        err("NPI", npi, "NPI must be exactly 10 digits.")

    # Rule 6: DOB format and validity
    dob = practitioner.get("dob", "").strip()
    if dob and not _is_valid_date(dob):
        err("DOB", dob, "DOB must be a valid date in MM-DD-YYYY format (e.g. 03-15-1980).")

    # Rule 7: State must be a valid US state code (if present)
    state = practitioner.get("state", "").strip()
    if state and state not in VALID_STATE_CODES:
        err("State", state, "State must be a valid 2-letter US state code (e.g. CA, NY).")

    # Rule 8: Zip 5 digits or ZIP+4 (12345 or 12345-6789).
    zip_code = practitioner.get("zip", "").strip()
    if zip_code and not _ZIP_RE.match(zip_code):
        err("Zip", zip_code, "Zip code must be 5 digits (12345) or ZIP+4 (12345-6789).")

    # Rules 9-12: Per-license field validation
    licenses = practitioner.get("licenses", [])
    for i, lic in enumerate(licenses):
        lic_label = f"License {i + 1}"

        # Rule 9: License Type — required + valid enum.
        # Required because Canvas's FHIR validator reads ``code.text`` from
        # this column with no fallback path; a blank Type produces an empty
        # ``code.text`` that the validator rejects.
        lic_type = lic.get("type", "").strip()
        if not lic_type:
            err(
                "License Type",
                "",
                f"{lic_label}: License Type is required. Must be one of: "
                f"{', '.join(sorted(VALID_LICENSE_TYPES))}.",
            )
        elif lic_type.lower() not in _VALID_LICENSE_TYPES_LOWER:
            err(
                "License Type",
                lic_type,
                f"{lic_label}: License Type must be one of {sorted(VALID_LICENSE_TYPES)}.",
            )

        # Rule 10: License State must be a valid US state code
        lic_state = lic.get("license_state", "").strip()
        if lic_state and lic_state not in VALID_STATE_CODES:
            err(
                "License State",
                lic_state,
                f"{lic_label}: License State must be a valid 2-letter US state code.",
            )

        # Rule 11: Issue/Expiration date format
        for date_field, human_label in (
            ("issue_date", "License Issue Date"),
            ("expiration_date", "License Expiration Date"),
        ):
            date_val = lic.get(date_field, "").strip()
            if date_val and not _is_valid_date(date_val):
                err(
                    human_label,
                    date_val,
                    f"{lic_label}: {human_label} must be a valid date in MM-DD-YYYY format (e.g. 03-15-1980).",
                )

        # Rule 12: Primary must be TRUE/YES/FALSE/NO (case-insensitive) or blank.
        primary_raw = lic.get("primary_raw", "").strip().upper()
        if primary_raw and primary_raw not in ("TRUE", "FALSE", "YES", "NO"):
            err(
                "Primary",
                lic.get("primary_raw", "").strip(),
                f"{lic_label}: Primary must be TRUE, FALSE, YES, or NO (blank is treated as FALSE).",
            )

    # Rule 13: Exactly one license should be primary
    if licenses:
        primary_count = sum(
            1
            for lic in licenses
            if lic.get("primary_raw", "").strip().upper() in ("TRUE", "YES")
        )
        if primary_count == 0:
            warn("No license is marked as primary (Primary = TRUE or YES).")
        elif primary_count > 1:
            warn(
                f"{primary_count} licenses are marked as primary; exactly one is expected."
            )

    # Rules 16 & 17: Conditional license field requirements. Canonicalise
    # the CSV value first — the template tells users to type ``STATE`` /
    # ``OTHER`` / ``PTAN`` but the parser also accepts the legacy alias
    # ``State license`` and case variants. Comparing the raw lowercased
    # form (e.g. ``"state"``) against literal phrases would silently miss
    # the canonical inputs the template recommends.
    for i, lic in enumerate(licenses):
        lic_label = f"License {i + 1}"
        canonical_type = canonicalize_license_type(lic.get("type", "").strip())

        # Rule 16: License Name is required when License Type is OTHER.
        if canonical_type == "OTHER":
            lic_name = lic.get("name", "").strip()
            if not lic_name:
                err(
                    "License Name",
                    lic_name,
                    f"{lic_label}: License Name is required when License Type is Other.",
                )

        # Rule 17: License State is required when License Type is STATE or PTAN.
        if canonical_type in ("STATE", "PTAN"):
            lic_state = lic.get("license_state", "").strip()
            if not lic_state:
                err(
                    "License State",
                    lic_state,
                    f"{lic_label}: License State is required when License Type is {canonical_type}.",
                )

    return errors, warnings


def validate_continuation_row(
    row_number: int,
    first_row: dict[str, str],
    continuation_row: dict[str, str],
) -> list[ValidationWarning]:
    """
    Rule 14: Warn if a continuation row has differing non-license demographic
    fields from the first row (first row wins).
    """
    warnings: list[ValidationWarning] = []
    demographic_fields = (
        "first_name",
        "last_name",
        "role",
        "phone",
        "fax",
        "npi",
        "dob",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "zip",
        "primary_practice_location",
    )
    for field in demographic_fields:
        first_val = first_row.get(field, "").strip()
        cont_val = continuation_row.get(field, "").strip()
        if cont_val and cont_val != first_val:
            human = field.replace("_", " ").title()
            warnings.append(
                ValidationWarning(
                    row_number,
                    f"Continuation row has a different {human} ('{cont_val}'); "
                    f"first-row value ('{first_val}') will be used.",
                )
            )
    return warnings
