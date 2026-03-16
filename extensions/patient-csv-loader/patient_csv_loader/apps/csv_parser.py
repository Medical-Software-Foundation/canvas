"""CSV parsing and validation for patient bulk loading.

Parses CSV content, validates each row against the spec, and returns
structured results (valid rows and error rows with details).

Note: Does NOT use Python's `csv` module because the Canvas plugin sandbox
does not allow it. CSV parsing is implemented manually instead.
"""

from __future__ import annotations

from datetime import date, datetime

REQUIRED_FIELDS = ("first_name", "last_name", "birthdate", "sex_at_birth", "phone")

VALID_SEX_AT_BIRTH = {"F", "M", "O", "UNK"}
VALID_ADDRESS_USE = {"home", "work", "temp", "old"}
VALID_CONTACT_SYSTEM = {"phone", "fax", "email", "pager", "other"}
VALID_CONTACT_USE = {"home", "work", "temp", "old", "other", "mobile", "automation"}

REQUIRED_ADDRESS_FIELDS = ("address_line1", "address_city", "address_state_code", "address_postal_code", "address_country")
ALL_ADDRESS_FIELDS = (*REQUIRED_ADDRESS_FIELDS, "address_line2", "address_use")

DEMOGRAPHIC_FIELDS = (
    "first_name", "last_name", "birthdate", "sex_at_birth", "phone",
    "middle_name", "prefix", "suffix", "nickname",
    "social_security_number", "administrative_note", "clinical_note",
)

CONTACT_FIELDS_PER_SLOT = ("system", "value", "use", "rank", "has_consent")
EXTERNAL_ID_FIELDS_PER_SLOT = ("system", "value")


class RowError:
    """A validation error for a single CSV row."""

    def __init__(self, row_number: int, errors: list[str], raw_data: dict[str, str]) -> None:
        self.row_number = row_number
        self.errors = errors
        self.raw_data = raw_data


class ValidRow:
    """A validated row ready for patient creation."""

    def __init__(self, row_number: int, data: dict[str, str]) -> None:
        self.row_number = row_number
        self.data = data


class ParseResult:
    """The result of parsing and validating a CSV file."""

    def __init__(self) -> None:
        self.valid_rows: list[ValidRow] = []
        self.error_rows: list[RowError] = []
        self.total_rows: int = 0


def _strip_bom(text: str) -> str:
    """Strip UTF-8 BOM if present."""
    return text.lstrip("\ufeff")


def _normalize_headers(headers: list[str]) -> list[str]:
    """Lowercase and strip whitespace from headers."""
    return [h.strip().lower() for h in headers]


def _parse_csv_line(line: str) -> list[str]:
    """Parse a single CSV line into fields, handling quoted values.

    Handles:
    - Comma-separated values
    - Double-quoted fields (containing commas, quotes, or whitespace)
    - Escaped quotes (doubled: "" inside a quoted field)
    """
    fields: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    length = len(line)

    while i < length:
        ch = line[i]

        if in_quotes:
            if ch == '"':
                # Check for escaped quote ""
                if i + 1 < length and line[i + 1] == '"':
                    current.append('"')
                    i = i + 2
                    continue
                else:
                    # End of quoted field
                    in_quotes = False
                    i = i + 1
                    continue
            else:
                current.append(ch)
                i = i + 1
        else:
            if ch == '"' and len(current) == 0:
                # Start of quoted field
                in_quotes = True
                i = i + 1
            elif ch == ',':
                fields.append("".join(current))
                current = []
                i = i + 1
            elif ch in ('\r', '\n'):
                i = i + 1
            else:
                current.append(ch)
                i = i + 1

    fields.append("".join(current))
    return fields


def _csv_escape(value: str) -> str:
    """Escape a value for CSV output — quote if it contains commas, quotes, or newlines."""
    if '"' in value or ',' in value or '\n' in value or '\r' in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def _to_digits(value: str) -> str:
    """Extract only digit characters from a string."""
    return "".join(ch for ch in value if ch.isdigit())


def _validate_required_fields(row: dict[str, str]) -> list[str]:
    """Check that all required fields are present and non-empty."""
    errors: list[str] = []
    for f in REQUIRED_FIELDS:
        val = row.get(f, "").strip()
        if not val:
            errors.append(f"{f} is required")
    return errors


def _validate_birthdate(value: str) -> list[str]:
    """Validate birthdate is a valid YYYY-MM-DD date."""
    value = value.strip()
    if not value:
        return []  # already caught by required field check
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        if parsed > date.today():
            return ["birthdate cannot be in the future"]
    except ValueError:
        return ["birthdate must be in YYYY-MM-DD format"]
    return []


def _validate_sex_at_birth(value: str) -> list[str]:
    """Validate sex_at_birth is one of the allowed values."""
    value = value.strip().upper()
    if not value:
        return []
    if value not in VALID_SEX_AT_BIRTH:
        return [f"sex_at_birth must be one of: {', '.join(sorted(VALID_SEX_AT_BIRTH))}"]
    return []


def _validate_phone(row: dict[str, str]) -> list[str]:
    """Validate required phone field is exactly 10 digits (per FHIR Patient spec)."""
    raw = row.get("phone", "").strip()
    if not raw:
        return []  # caught by required field check
    digits = _to_digits(raw)
    if len(digits) != 10:
        return ["phone must be 10 digits (e.g. 555-123-4567 or 5551234567)"]
    return []


def _validate_address(row: dict[str, str]) -> list[str]:
    """Validate address fields — if any are present, required address fields must be filled."""
    errors: list[str] = []
    has_any_address = any(row.get(f, "").strip() for f in ALL_ADDRESS_FIELDS)
    if not has_any_address:
        return []

    for f in REQUIRED_ADDRESS_FIELDS:
        if not row.get(f, "").strip():
            errors.append(f"{f} is required when any address field is provided")

    # State code must be 2 letters (e.g. CA, NY, IL)
    state = row.get("address_state_code", "").strip()
    if state:
        if len(state) != 2 or not state.isalpha():
            errors.append("address_state_code must be a 2-letter state abbreviation (e.g. CA, NY)")

    # Postal code must be 5 digits
    postal = row.get("address_postal_code", "").strip()
    if postal:
        postal_digits = _to_digits(postal)
        if len(postal_digits) != 5:
            errors.append("address_postal_code must be 5 digits (e.g. 90210)")

    # Country must be 2-letter ISO code
    country = row.get("address_country", "").strip()
    if country:
        if len(country) != 2 or not country.isalpha():
            errors.append("address_country must be a 2-letter country code (e.g. US)")

    use = row.get("address_use", "").strip().lower()
    if use and use not in VALID_ADDRESS_USE:
        errors.append(f"address_use must be one of: {', '.join(sorted(VALID_ADDRESS_USE))}")

    return errors


def _validate_contact_slot(row: dict[str, str], slot: int) -> list[str]:
    """Validate a single contact point slot (1 or 2)."""
    errors: list[str] = []
    prefix = f"contact_{slot}_"

    system = row.get(f"{prefix}system", "").strip().lower()
    value = row.get(f"{prefix}value", "").strip()
    use = row.get(f"{prefix}use", "").strip().lower()
    rank = row.get(f"{prefix}rank", "").strip()
    has_consent = row.get(f"{prefix}has_consent", "").strip().lower()

    has_any = any([system, value, use, rank, has_consent])
    if not has_any:
        return []

    if system and not value:
        errors.append(f"contact_{slot}_value is required when contact_{slot}_system is provided")
    if not system and value:
        errors.append(f"contact_{slot}_system is required when contact_{slot}_value is provided")

    if system and system not in VALID_CONTACT_SYSTEM:
        errors.append(
            f"contact_{slot}_system must be one of: {', '.join(sorted(VALID_CONTACT_SYSTEM))}"
        )

    # FHIR requires phone numbers to be exactly 10 digits
    if system == "phone" and value:
        phone_digits = _to_digits(value)
        if len(phone_digits) != 10:
            errors.append(
                f"contact_{slot}_value must be 10 digits when system is phone"
            )

    if use and use not in VALID_CONTACT_USE:
        errors.append(
            f"contact_{slot}_use must be one of: {', '.join(sorted(VALID_CONTACT_USE))}"
        )

    if rank:
        try:
            rank_int = int(rank)
            if rank_int < 1:
                errors.append(f"contact_{slot}_rank must be a positive integer")
        except ValueError:
            errors.append(f"contact_{slot}_rank must be a positive integer")

    if has_consent and has_consent not in ("true", "false"):
        errors.append(f"contact_{slot}_has_consent must be true or false")

    return errors


def _validate_ssn(row: dict[str, str]) -> list[str]:
    """Validate social_security_number is 9 digits (with optional dashes/spaces)."""
    raw = row.get("social_security_number", "").strip()
    if not raw:
        return []
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 9:
        return ["social_security_number must be 9 digits (e.g. 123-45-6789 or 123456789)"]
    return []


def _validate_external_id_slot(row: dict[str, str], slot: int) -> list[str]:
    """Validate a single external identifier slot (1, 2, or 3)."""
    errors: list[str] = []
    system = row.get(f"external_id_{slot}_system", "").strip()
    value = row.get(f"external_id_{slot}_value", "").strip()

    if system and not value:
        errors.append(f"external_id_{slot}_value is required when external_id_{slot}_system is provided")
    if value and not system:
        errors.append(f"external_id_{slot}_system is required when external_id_{slot}_value is provided")

    return errors


def validate_row(row: dict[str, str]) -> list[str]:
    """Validate a single CSV row. Returns a list of error messages (empty if valid)."""
    errors: list[str] = []
    errors.extend(_validate_required_fields(row))
    errors.extend(_validate_birthdate(row.get("birthdate", "")))
    errors.extend(_validate_sex_at_birth(row.get("sex_at_birth", "")))
    errors.extend(_validate_phone(row))
    errors.extend(_validate_ssn(row))
    errors.extend(_validate_address(row))
    for slot in (1, 2):
        errors.extend(_validate_contact_slot(row, slot))
    for slot in (1, 2, 3):
        errors.extend(_validate_external_id_slot(row, slot))
    return errors


def parse_csv(csv_content: str) -> ParseResult:
    """Parse CSV content and validate all rows.

    Args:
        csv_content: Raw CSV text (may include BOM).

    Returns:
        ParseResult with valid_rows, error_rows, and total_rows.
    """
    csv_content = _strip_bom(csv_content)

    lines = csv_content.splitlines()
    if not lines:
        return ParseResult()

    # Parse header line
    raw_headers = _parse_csv_line(lines[0])
    if not raw_headers:
        return ParseResult()
    normalized_headers = _normalize_headers(raw_headers)

    result = ParseResult()
    total = 0
    for i, line in enumerate(lines[1:], start=2):  # row 1 is the header
        if not line.strip():
            continue
        total = total + 1
        fields = _parse_csv_line(line)

        # Build row dict from headers and fields
        row: dict[str, str] = {}
        for idx, header in enumerate(normalized_headers):
            if not header:
                continue
            value = fields[idx] if idx < len(fields) else ""
            row[header] = value.strip()

        errors = validate_row(row)
        if errors:
            result.error_rows.append(RowError(row_number=i, errors=errors, raw_data=row))
        else:
            result.valid_rows.append(ValidRow(row_number=i, data=row))

    result.total_rows = total
    return result


def generate_template_csv() -> str:
    """Generate a CSV template with all headers and one example row."""
    headers = [
        "first_name", "last_name", "birthdate", "sex_at_birth", "phone",
        "middle_name", "prefix", "suffix", "nickname",
        "social_security_number", "administrative_note", "clinical_note",
        "address_line1", "address_line2", "address_city", "address_state_code",
        "address_postal_code", "address_country", "address_use",
        "contact_1_system", "contact_1_value", "contact_1_use", "contact_1_rank", "contact_1_has_consent",
        "contact_2_system", "contact_2_value", "contact_2_use", "contact_2_rank", "contact_2_has_consent",
        "external_id_1_system", "external_id_1_value",
        "external_id_2_system", "external_id_2_value",
        "external_id_3_system", "external_id_3_value",
    ]
    example_row = [
        "Jane", "Doe", "1985-03-15", "F", "(555) 123-4567",
        "Marie", "Ms.", "Jr.", "Janie",
        "123-45-6789", "New patient from EHR migration", "No known allergies",
        "123 Main St", "Apt 4B", "Springfield", "IL",
        "62701", "US", "home",
        "email", "jane.doe@example.com", "home", "2", "true",
        "", "", "", "", "",
        "http://old-ehr.example.com", "PAT-001",
        "", "",
        "", "",
    ]

    header_line = ",".join(_csv_escape(h) for h in headers)
    example_line = ",".join(_csv_escape(v) for v in example_row)
    return header_line + "\r\n" + example_line + "\r\n"
