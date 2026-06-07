"""CSV parsing for lab order favorites bulk upload.

Does NOT use Python's `csv` module - the Canvas plugin sandbox does not allow
it, so CSV parsing is implemented manually. Handles BOM, quoted fields, and
escaped quotes. Structural validation only (required columns, value formats);
lab partner and test-code validation against the instance catalog happens in
the service layer where the database is available.
"""

from __future__ import annotations

REQUIRED_FIELDS = ("name", "lab_partner", "test_order_codes")

ALL_FIELDS = (
    "name",
    "lab_partner",
    "test_order_codes",
    "tags",
    "is_shared",
    "fasting_required",
    "comment",
    "diagnosis_codes",
)

_TRUE_VALUES = {"true", "1", "yes", "y"}
_FALSE_VALUES = {"false", "0", "no", "n", ""}


class ParsedRow:
    """A structurally valid favorite row, ready for catalog validation."""

    def __init__(
        self,
        row_number: int,
        name: str,
        lab_partner: str,
        order_codes: list[str],
        tags: list[str],
        is_shared: bool,
        fasting_required: bool,
        comment: str,
        diagnosis_codes: list[str],
    ) -> None:
        self.row_number = row_number
        self.name = name
        self.lab_partner = lab_partner
        self.order_codes = order_codes
        self.tags = tags
        self.is_shared = is_shared
        self.fasting_required = fasting_required
        self.comment = comment
        self.diagnosis_codes = diagnosis_codes


class RowError:
    """A structural validation error for a single CSV row."""

    def __init__(self, row_number: int, errors: list[str], raw_data: dict[str, str]) -> None:
        self.row_number = row_number
        self.errors = errors
        self.raw_data = raw_data


class ParseResult:
    """The result of parsing and structurally validating a favorites CSV."""

    def __init__(self) -> None:
        self.parsed_rows: list[ParsedRow] = []
        self.error_rows: list[RowError] = []
        self.total_rows: int = 0


def _strip_bom(text: str) -> str:
    """Strip a UTF-8 BOM if present."""
    return text.lstrip("﻿")


def _normalize_headers(headers: list[str]) -> list[str]:
    """Lowercase and strip whitespace from headers."""
    return [h.strip().lower() for h in headers]


def _parse_csv_line(line: str) -> list[str]:
    """Parse a single CSV line into fields, handling quoted values."""
    fields: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    length = len(line)

    while i < length:
        ch = line[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < length and line[i + 1] == '"':
                    current.append('"')
                    i = i + 2
                    continue
                in_quotes = False
                i = i + 1
                continue
            current.append(ch)
            i = i + 1
        else:
            if ch == '"' and len(current) == 0:
                in_quotes = True
                i = i + 1
            elif ch == ",":
                fields.append("".join(current))
                current = []
                i = i + 1
            elif ch in ("\r", "\n"):
                i = i + 1
            else:
                current.append(ch)
                i = i + 1

    fields.append("".join(current))
    return fields


def _csv_escape(value: str) -> str:
    """Escape a value for CSV output."""
    if '"' in value or "," in value or "\n" in value or "\r" in value:
        return '"' + value.replace('"', '""') + '"'
    return value


def _split_multi(value: str) -> list[str]:
    """Split a semicolon-separated cell into a list of trimmed, non-empty parts."""
    return [part.strip() for part in value.split(";") if part.strip()]


def _parse_bool(value: str, field: str, default: bool) -> tuple[bool, list[str]]:
    """Parse a boolean cell. Returns (value, errors)."""
    raw = value.strip().lower()
    if raw == "":
        return default, []
    if raw in _TRUE_VALUES:
        return True, []
    if raw in _FALSE_VALUES:
        return False, []
    return default, [f"{field} must be true or false"]


def parse_favorites_csv(csv_content: str) -> ParseResult:
    """Parse favorites CSV content and structurally validate every row."""
    csv_content = _strip_bom(csv_content)
    lines = csv_content.splitlines()
    result = ParseResult()
    if not lines:
        return result

    raw_headers = _parse_csv_line(lines[0])
    if not raw_headers:  # pragma: no cover - _parse_csv_line always returns at least [""]
        return result
    headers = _normalize_headers(raw_headers)

    total = 0
    for line_index, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        total = total + 1
        fields = _parse_csv_line(line)

        row: dict[str, str] = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            value = fields[idx] if idx < len(fields) else ""
            row[header] = value.strip()

        errors: list[str] = []
        for f in ("name", "lab_partner"):
            if not row.get(f, "").strip():
                errors.append(f"{f} is required")

        order_codes = _split_multi(row.get("test_order_codes", ""))
        if not order_codes:
            errors.append("test_order_codes must contain at least one code")

        is_shared, shared_errors = _parse_bool(
            row.get("is_shared", ""), "is_shared", True
        )
        errors.extend(shared_errors)

        fasting_required, fasting_errors = _parse_bool(
            row.get("fasting_required", ""), "fasting_required", False
        )
        errors.extend(fasting_errors)

        if errors:
            result.error_rows.append(
                RowError(row_number=line_index, errors=errors, raw_data=row)
            )
            continue

        result.parsed_rows.append(
            ParsedRow(
                row_number=line_index,
                name=row.get("name", "").strip(),
                lab_partner=row.get("lab_partner", "").strip(),
                order_codes=order_codes,
                tags=_split_multi(row.get("tags", "")),
                is_shared=is_shared,
                fasting_required=fasting_required,
                comment=row.get("comment", "").strip(),
                diagnosis_codes=_split_multi(row.get("diagnosis_codes", "")),
            )
        )

    result.total_rows = total
    return result


def generate_template_csv() -> str:
    """Generate a CSV template with headers and one example row."""
    headers = list(ALL_FIELDS)
    example_row = [
        "Annual Wellness Panel",
        "LabCorp",
        "001453;322000;001065",
        "wellness;annual",
        "true",
        "false",
        "Fasting 8h preferred",
        "Z00.00",
    ]
    header_line = ",".join(_csv_escape(h) for h in headers)
    example_line = ",".join(_csv_escape(v) for v in example_row)
    return header_line + "\r\n" + example_line + "\r\n"
