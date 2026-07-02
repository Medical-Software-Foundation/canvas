"""CSV parsing, validation, and record grouping for bulk availability import.

Parses a CSV of availability rows, validates each row structurally, and groups
rows into ProviderAvailabilityRule / AdminBlock / RecurringBlock records.

Three row types via the ``type`` column:
- ``rule``   a bookable availability window (weekly or daily)
- ``block``  a one-off unavailable date or time range
- ``rblock`` a recurring unavailable window (weekly or daily), optional hold

Note: does NOT use Python's ``csv`` module. The Canvas plugin sandbox does not
allow it, so CSV parsing is implemented manually (see ``_parse_csv_line``).

Rows are keyed by ``staff_key`` (the Canvas Staff UUID), which works for
providers, non-provider staff, and any schedulable staff record - unlike NPI,
which only providers have.

Parsing, structural validation, and grouping are all DB-free so they can be unit
tested without mocking Canvas data models. Validation of the staff key and
name-to-ID resolution (location, visit type) happen in the API layer where
batched DB access lives.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

DAYS_OF_WEEK = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

ROW_TYPES = ("rule", "block", "rblock")
VALID_FREQUENCIES = ("weekly", "daily")
VALID_HOLD_TYPES = ("none", "same_day", "next_day")

TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

TEMPLATE_HEADERS = (
    "type",
    "staff_key",
    "location",
    "visit_type",
    "day",
    "start",
    "end",
    "all_day",
    "date",
    "reason",
    "hold_type",
    "buffer_pre",
    "buffer_post",
    "min_lead_hours",
    "slot_minutes",
    "recurrence_frequency",
    "recurrence_interval",
    "effective_start",
    "effective_end",
    "group_key",
)


class RowError:
    """A validation error for a single CSV row."""

    def __init__(self, row_number: int, errors: list[str], raw_data: dict[str, str]) -> None:
        self.row_number = row_number
        self.errors = errors
        self.raw_data = raw_data


class ValidRow:
    """A structurally-valid row ready for name resolution and grouping."""

    def __init__(self, row_number: int, data: dict[str, str]) -> None:
        self.row_number = row_number
        self.data = data


class ParseResult:
    """The result of parsing and structurally validating a CSV file."""

    def __init__(self) -> None:
        self.valid_rows: list[ValidRow] = []
        self.error_rows: list[RowError] = []
        self.total_rows: int = 0


# -- Low-level CSV parsing (sandbox-safe, no csv module) --------------------


def _strip_bom(text: str) -> str:
    """Strip a UTF-8 BOM if present."""
    return text.lstrip("﻿")


def _normalize_headers(headers: list[str]) -> list[str]:
    """Lowercase and strip whitespace from headers."""
    return [h.strip().lower() for h in headers]


def _parse_csv_line(line: str) -> list[str]:
    """Parse a single CSV line into fields, handling quoted values.

    Handles comma-separated values, double-quoted fields (which may contain
    commas or quotes), and escaped quotes (doubled ``""`` inside a quoted field).
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
                if i + 1 < length and line[i + 1] == '"':
                    current.append('"')
                    i = i + 2
                    continue
                else:
                    in_quotes = False
                    i = i + 1
                    continue
            else:
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
    """Escape a value for CSV output: quote if it contains a comma, quote, or newline."""
    if '"' in value or "," in value or "\n" in value or "\r" in value:
        return '"' + value.replace('"', '""') + '"'
    return value


# -- Field validators -------------------------------------------------------


def _is_valid_time(value: str) -> bool:
    return bool(TIME_RE.match(value))


def _is_valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _validate_int(value: str, field: str, minimum: int) -> tuple[int | None, str | None]:
    """Parse a non-empty integer field. Returns (value, error)."""
    try:
        parsed = int(value)
    except ValueError:
        return None, f"{field} must be a whole number"
    if parsed < minimum:
        return None, f"{field} must be >= {minimum}"
    return parsed, None


def _validate_window(row: dict[str, str]) -> list[str]:
    """Validate start/end are HH:MM and start < end."""
    errors: list[str] = []
    start = row.get("start", "").strip()
    end = row.get("end", "").strip()
    if not _is_valid_time(start):
        errors.append("start must be HH:MM (24-hour)")
    if not _is_valid_time(end):
        errors.append("end must be HH:MM (24-hour)")
    if not errors and start >= end:
        errors.append(f"start must be before end ({start} >= {end})")
    return errors


def _validate_recurrence(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    freq = (row.get("recurrence_frequency", "").strip() or "weekly").lower()
    if freq not in VALID_FREQUENCIES:
        errors.append(f"recurrence_frequency must be one of: {', '.join(VALID_FREQUENCIES)}")
    interval = row.get("recurrence_interval", "").strip()
    if interval:
        _, err = _validate_int(interval, "recurrence_interval", 1)
        if err:
            errors.append(err)
    return errors


def _validate_optional_date(row: dict[str, str], field: str) -> list[str]:
    val = row.get(field, "").strip()
    if val and not _is_valid_date(val):
        return [f"{field} must be YYYY-MM-DD"]
    return []


def _validate_optional_int(row: dict[str, str], field: str, minimum: int) -> list[str]:
    val = row.get(field, "").strip()
    if not val:
        return []
    _, err = _validate_int(val, field, minimum)
    return [err] if err else []


def _validate_rule_row(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    freq = (row.get("recurrence_frequency", "").strip() or "weekly").lower()
    if freq == "weekly":
        day = row.get("day", "").strip().lower()
        if day not in DAYS_OF_WEEK:
            errors.append(f"day must be one of: {', '.join(DAYS_OF_WEEK)}")
    errors.extend(_validate_window(row))
    errors.extend(_validate_recurrence(row))
    for f in ("buffer_pre", "buffer_post", "min_lead_hours"):
        errors.extend(_validate_optional_int(row, f, 0))
    errors.extend(_validate_optional_int(row, "slot_minutes", 1))
    errors.extend(_validate_optional_date(row, "effective_start"))
    errors.extend(_validate_optional_date(row, "effective_end"))
    return errors


def _validate_block_row(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    block_date = row.get("date", "").strip()
    if not block_date:
        errors.append("date is required for a block row")
    elif not _is_valid_date(block_date):
        errors.append("date must be YYYY-MM-DD")
    all_day = _truthy(row.get("all_day", ""))
    if not all_day:
        errors.extend(_validate_window(row))
    return errors


def _validate_rblock_row(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    freq = (row.get("recurrence_frequency", "").strip() or "weekly").lower()
    if freq == "weekly":
        day = row.get("day", "").strip().lower()
        if day not in DAYS_OF_WEEK:
            errors.append(f"day must be one of: {', '.join(DAYS_OF_WEEK)}")
    errors.extend(_validate_window(row))
    errors.extend(_validate_recurrence(row))
    hold = row.get("hold_type", "").strip().lower()
    if hold and hold not in VALID_HOLD_TYPES:
        errors.append(f"hold_type must be one of: {', '.join(VALID_HOLD_TYPES)}")
    errors.extend(_validate_optional_date(row, "effective_start"))
    errors.extend(_validate_optional_date(row, "effective_end"))
    return errors


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes", "y")


def validate_row(row: dict[str, str]) -> list[str]:
    """Validate a single CSV row structurally. Returns a list of error messages."""
    row_type = row.get("type", "").strip().lower()
    if row_type not in ROW_TYPES:
        return [f"type must be one of: {', '.join(ROW_TYPES)}"]
    if not row.get("staff_key", "").strip():
        return ["staff_key is required"]

    if row_type == "rule":
        return _validate_rule_row(row)
    if row_type == "block":
        return _validate_block_row(row)
    return _validate_rblock_row(row)


def parse_csv(csv_content: str) -> ParseResult:
    """Parse CSV content and structurally validate every row."""
    csv_content = _strip_bom(csv_content)
    lines = csv_content.splitlines()
    result = ParseResult()
    if not lines:
        return result

    raw_headers = _parse_csv_line(lines[0])
    if not raw_headers:
        return result
    normalized_headers = _normalize_headers(raw_headers)

    total = 0
    for i, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        total = total + 1
        fields = _parse_csv_line(line)

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


# -- Record grouping (DB-free; takes pre-built name-to-id maps) --------------


def _window(row: dict[str, str]) -> dict[str, str]:
    return {"start": row["start"].strip(), "end": row["end"].strip()}


def _windows_overlap(a: dict[str, str], b: dict[str, str]) -> bool:
    return a["start"] < b["end"] and b["start"] < a["end"]


def _resolve_names(
    names: str,
    name_map: dict[str, str],
    field: str,
) -> tuple[list[str], list[str]]:
    """Resolve a ``|``-separated list of names to IDs via name_map.

    Returns (ids, errors). Empty input resolves to an empty id list (means "all").
    """
    ids: list[str] = []
    errors: list[str] = []
    for raw in names.split("|"):
        name = raw.strip()
        if not name:
            continue
        resolved = name_map.get(name.lower())
        if resolved is None:
            errors.append(f"{field} '{name}' not found")
        else:
            ids.append(resolved)
    return ids, errors


def _rule_signature(
    row: dict[str, str],
    provider_id: str,
    location_ids: list[str],
    visit_types: list[str],
) -> tuple:
    """Grouping signature: rows sharing it merge into one rule/recurring-block."""
    group_key = row.get("group_key", "").strip()
    if group_key:
        return (provider_id, group_key, row.get("type", ""))
    freq = (row.get("recurrence_frequency", "").strip() or "weekly").lower()
    return (
        provider_id,
        row.get("type", ""),
        tuple(sorted(location_ids)),
        tuple(sorted(visit_types)),
        row.get("effective_start", "").strip(),
        row.get("effective_end", "").strip(),
        row.get("buffer_pre", "").strip(),
        row.get("buffer_post", "").strip(),
        row.get("min_lead_hours", "").strip(),
        row.get("slot_minutes", "").strip(),
        freq,
        row.get("recurrence_interval", "").strip() or "1",
        row.get("hold_type", "").strip().lower() or "none",
    )


def _or_none(value: str) -> str | None:
    return value.strip() or None


def build_records(
    valid_rows: list[ValidRow],
    valid_staff_ids: set[str],
    location_map: dict[str, str],
    visit_type_map: dict[str, str],
) -> tuple[list[dict[str, Any]], list[RowError]]:
    """Validate staff keys, resolve names to IDs, and group rows into records.

    ``staff_key`` is used directly as the record's ``provider_id`` (it is the
    Canvas Staff UUID). Each returned record is a dict ready for the matching
    model ``from_dict``, tagged with ``kind`` (``rule``|``block``|``rblock``)
    and the source row numbers. Rows with an unknown staff key or an
    unresolvable location/visit type are returned as errors instead.
    """
    records: list[dict[str, Any]] = []
    errors: list[RowError] = []

    grouped: dict[tuple, dict[str, Any]] = {}

    for vr in valid_rows:
        row = vr.data
        row_type = row["type"].strip().lower()

        provider_id = row["staff_key"].strip()
        if provider_id not in valid_staff_ids:
            errors.append(
                RowError(vr.row_number, [f"staff_key '{provider_id}' not found among active staff"], row)
            )
            continue

        location_ids, loc_errs = _resolve_names(row.get("location", ""), location_map, "location")
        row_errors = list(loc_errs)
        visit_types: list[str] = []
        if row_type == "rule":
            visit_types, vt_errs = _resolve_names(row.get("visit_type", ""), visit_type_map, "visit_type")
            row_errors.extend(vt_errs)
        if row_errors:
            errors.append(RowError(vr.row_number, row_errors, row))
            continue

        if row_type == "block":
            records.append(_build_block_record(vr, provider_id, location_ids))
            continue

        sig = _rule_signature(row, provider_id, location_ids, visit_types)
        if sig not in grouped:
            grouped[sig] = _new_group(row_type, row, provider_id, location_ids, visit_types)
        group = grouped[sig]

        window = _window(row)
        add_err = _add_window_to_group(group, row, window)
        if add_err:
            errors.append(RowError(vr.row_number, [add_err], row))
        else:
            group["source_rows"].append(vr.row_number)

    records.extend(grouped.values())
    return records, errors


def _new_group(
    row_type: str,
    row: dict[str, str],
    provider_id: str,
    location_ids: list[str],
    visit_types: list[str],
) -> dict[str, Any]:
    freq = (row.get("recurrence_frequency", "").strip() or "weekly").lower()
    interval_str = row.get("recurrence_interval", "").strip()
    interval = int(interval_str) if interval_str else 1
    group: dict[str, Any] = {
        "kind": row_type,
        "source_rows": [],
        "provider_id": provider_id,
        "location_ids": location_ids,
        "weekly_schedule": {},
        "time_windows": [],
        "recurrence_frequency": freq,
        "recurrence_interval": interval,
        "reason": row.get("reason", "").strip(),
        "effective_start": _or_none(row.get("effective_start", "")),
        "effective_end": _or_none(row.get("effective_end", "")),
        "is_active": True,
    }
    if row_type == "rule":
        group["visit_types"] = visit_types
        buffer_pre = row.get("buffer_pre", "").strip()
        buffer_post = row.get("buffer_post", "").strip()
        group["buffer_minutes"] = {
            "pre": int(buffer_pre) if buffer_pre else 0,
            "post": int(buffer_post) if buffer_post else 15,
        }
        min_lead = row.get("min_lead_hours", "").strip()
        slot = row.get("slot_minutes", "").strip()
        group["booking_interval"] = {
            "min_lead_hours": int(min_lead) if min_lead else 24,
            "slot_granularity_minutes": int(slot) if slot else 15,
        }
    else:  # rblock
        group["hold_type"] = row.get("hold_type", "").strip().lower() or "none"
    return group


def _add_window_to_group(
    group: dict[str, Any],
    row: dict[str, str],
    window: dict[str, str],
) -> str | None:
    """Add a time window to a group, guarding against overlaps. Returns an error string or None."""
    if group["recurrence_frequency"] == "daily":
        existing = group["time_windows"]
        for w in existing:
            if _windows_overlap(w, window):
                return f"window {window['start']}-{window['end']} overlaps another window in the same daily group"
        existing.append(window)
        return None
    day = row["day"].strip().lower()
    day_windows = group["weekly_schedule"].setdefault(day, [])
    for w in day_windows:
        if _windows_overlap(w, window):
            return f"window {window['start']}-{window['end']} overlaps another {day} window in the same group"
    day_windows.append(window)
    return None


def _build_block_record(vr: ValidRow, provider_id: str, location_ids: list[str]) -> dict[str, Any]:
    row = vr.data
    block_date = row["date"].strip()
    all_day = _truthy(row.get("all_day", ""))
    if all_day:
        start_iso = f"{block_date}T00:00:00"
        end_iso = f"{block_date}T23:59:59"
    else:
        start_iso = f"{block_date}T{row['start'].strip()}:00"
        end_iso = f"{block_date}T{row['end'].strip()}:00"
    return {
        "kind": "block",
        "source_rows": [vr.row_number],
        "provider_id": provider_id,
        "location_ids": location_ids,
        "start": start_iso,
        "end": end_iso,
        "all_day": all_day,
        "reason": row.get("reason", "").strip(),
    }


# -- Template ---------------------------------------------------------------


def generate_template_csv() -> str:
    """Generate a CSV template with headers and one example of each row type."""
    examples = [
        ["rule", "11111111-1111-1111-1111-111111111111", "Main Clinic", "", "monday", "09:00", "12:00", "", "", "",
         "", "0", "15", "24", "15", "weekly", "1", "2026-07-01", "", ""],
        ["rule", "11111111-1111-1111-1111-111111111111", "Main Clinic", "", "monday", "13:00", "17:00", "", "", "",
         "", "0", "15", "24", "15", "weekly", "1", "2026-07-01", "", ""],
        ["block", "11111111-1111-1111-1111-111111111111", "", "", "", "", "", "true", "2026-07-04", "Independence Day",
         "", "", "", "", "", "", "", "", "", ""],
        ["rblock", "11111111-1111-1111-1111-111111111111", "", "", "monday", "12:00", "13:00", "", "", "Lunch",
         "none", "", "", "", "", "weekly", "1", "", "", ""],
    ]
    header_line = ",".join(_csv_escape(h) for h in TEMPLATE_HEADERS)
    lines = [header_line]
    for ex in examples:
        lines.append(",".join(_csv_escape(v) for v in ex))
    return "\r\n".join(lines) + "\r\n"
