"""
CSV parsing and grouping logic for the practitioner bulk loader.

Parses raw CSV text into merged practitioner records grouped by email.
"""

from __future__ import annotations

import re
from typing import Any

from practitioner_bulk_loader.utils.validation import (
    canonicalize_license_type,
    to_fhir_date,
    validate_continuation_row,
)

# Strip common invisible Unicode chars that survive a copy-paste out of
# Word/Excel/Google Docs: zero-width space, zero-width non-joiner,
# zero-width joiner, and the UTF-8 BOM. Without this, cells look correct
# to a human but fail every regex-based validation.
_INVISIBLE_CHARS_RE = re.compile(r"[​‌‍﻿]")


def _clean_cell(value: str) -> str:
    return _INVISIBLE_CHARS_RE.sub("", value or "").strip()


# Hand-built map of common Western/European accented characters to their
# ASCII equivalents. Canvas's RestrictedPython sandbox blocks ``unicodedata``,
# so the obvious ``unicodedata.normalize("NFKD", ...)`` approach is not
# available. Anything not in this map and not ASCII just gets dropped.
_ASCII_FOLDS = str.maketrans({
    # a-family
    "á": "a", "à": "a", "â": "a", "ä": "a", "ã": "a", "å": "a", "ā": "a",
    "Á": "a", "À": "a", "Â": "a", "Ä": "a", "Ã": "a", "Å": "a", "Ā": "a",
    # e-family
    "é": "e", "è": "e", "ê": "e", "ë": "e", "ē": "e", "ė": "e", "ę": "e",
    "É": "e", "È": "e", "Ê": "e", "Ë": "e", "Ē": "e", "Ė": "e", "Ę": "e",
    # i-family
    "í": "i", "ì": "i", "î": "i", "ï": "i", "ī": "i", "į": "i",
    "Í": "i", "Ì": "i", "Î": "i", "Ï": "i", "Ī": "i", "Į": "i",
    # o-family
    "ó": "o", "ò": "o", "ô": "o", "ö": "o", "õ": "o", "ø": "o", "ō": "o",
    "Ó": "o", "Ò": "o", "Ô": "o", "Ö": "o", "Õ": "o", "Ø": "o", "Ō": "o",
    # u-family
    "ú": "u", "ù": "u", "û": "u", "ü": "u", "ū": "u", "ů": "u", "ű": "u",
    "Ú": "u", "Ù": "u", "Û": "u", "Ü": "u", "Ū": "u", "Ů": "u", "Ű": "u",
    # other single-letter folds
    "ñ": "n", "Ñ": "n", "ç": "c", "Ç": "c", "ý": "y", "ÿ": "y", "Ý": "y",
    "š": "s", "Š": "s", "ž": "z", "Ž": "z", "č": "c", "Č": "c",
    # ligatures / multi-letter folds
    "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ß": "ss",
})


def _sanitize_username_token(value: str) -> str:
    """Strip a name fragment to ASCII alphanumeric, lowercased.

    Folds common Western European accented characters to their ASCII
    equivalents (``José`` → ``jose``, ``Müller`` → ``muller``) using a
    hand-rolled translation map. Anything not in the map and not basic
    ASCII is dropped — spaces, punctuation, emoji, and non-Latin scripts
    (CJK, Arabic, etc.) all yield empty for that fragment.
    """
    if not value:
        return ""
    folded = value.translate(_ASCII_FOLDS)
    return "".join(c for c in folded if c.isascii() and c.isalnum()).lower()


def build_username(first_name: str, last_name: str) -> str:
    """Return a ``first.last`` username for the practitioner-user-username
    extension on the FHIR Practitioner resource.

    Setting this explicitly avoids Canvas's auto-generated default
    (e.g. ``mariagarcia``) — which collides whenever a Staff record with
    the same first+last name already exists. Returns an empty string if
    either fragment sanitizes to nothing (e.g. all non-ASCII characters);
    callers should then omit the extension and let Canvas decide.
    """
    first = _sanitize_username_token(first_name)
    last = _sanitize_username_token(last_name)
    if not first or not last:
        return ""
    return f"{first}.{last}"

# Placeholder NPI used when the CSV row leaves the NPI column blank.
# This is a known sentinel value meaning "no NPI on file."
DEFAULT_NPI = "1111155556"


def license_name_fallback(code_text: str, license_state: str) -> str:
    """Return the fallback string used when a License Name is blank.

    Combines the License Type with the License State (e.g. "STATE AK"),
    or just the License Type when no state is applicable (e.g. "DEA").
    Empty-string output when neither input has content.

    Used both at create time (CSV License Name blank → fall back) and
    at merge time (existing qualification has blank ``issuer.display``
    or short-name extension ``valueString`` → sanitiser fills the slot).
    Canvas's PUT validator rejects empty values in those slots, so a
    non-empty fallback is required to keep the merge from failing on
    legacy records that were saved without a Name.
    """
    parts = [s for s in (code_text.strip(), license_state.strip()) if s]
    return " ".join(parts)


def _parse_csv_rows(csv_text: str) -> list[list[str]]:
    """RFC 4180 CSV parser. Canvas sandbox blocks `import csv`, so we do it by hand.

    Handles quoted fields with embedded commas, newlines, and escaped `""`.
    """
    text = csv_text.replace("\r\n", "\n").replace("\r", "\n")
    rows: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    in_quotes = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_quotes:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field.append('"')
                    i += 2
                    continue
                in_quotes = False
                i += 1
                continue
            field.append(c)
            i += 1
            continue
        if c == '"' and not field:
            in_quotes = True
            i += 1
            continue
        if c == ",":
            row.append("".join(field))
            field = []
            i += 1
            continue
        if c == "\n":
            row.append("".join(field))
            rows.append(row)
            row = []
            field = []
            i += 1
            continue
        field.append(c)
        i += 1
    if field or row:
        row.append("".join(field))
        rows.append(row)
    return [r for r in rows if any(cell.strip() for cell in r)]

# ---------------------------------------------------------------------------
# CSV column headers (canonical names)
# ---------------------------------------------------------------------------

REQUIRED_HEADERS = [
    "First Name",
    "Last Name",
    "Role",
    "Email",
    "Phone",
    "DOB",
    "Primary Practice Location",
]

OPTIONAL_HEADERS = [
    "Fax",
    "NPI",
    "Address Line 1",
    "Address Line 2",
    "City",
    "State",
    "Zip",
    "License Type",
    "License Name",
    "License State",
    "License Number",
    "License Issue Date",
    "License Expiration Date",
    "Primary",
]

ALL_HEADERS = REQUIRED_HEADERS + OPTIONAL_HEADERS

# Mapping from CSV header -> internal key
_HEADER_MAP: dict[str, str] = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Role": "role",
    "Email": "email",
    "Phone": "phone",
    "DOB": "dob",
    "Primary Practice Location": "primary_practice_location",
    "Fax": "fax",
    "NPI": "npi",
    "Address Line 1": "address_line1",
    "Address Line 2": "address_line2",
    "City": "city",
    "State": "state",
    "Zip": "zip",
    "License Type": "license_type",
    "License Name": "license_name",
    "License State": "license_state",
    "License Number": "license_number",
    "License Issue Date": "license_issue_date",
    "License Expiration Date": "license_expiration_date",
    # Canonical header is "Primary"; "License Primary" is accepted for back-compat
    # with templates generated by earlier versions of the plugin.
    "Primary": "license_primary",
    "License Primary": "license_primary",
}

# Values accepted as truthy for the "Primary" column. Comparison is
# case-insensitive. Blank/FALSE/NO are treated as falsy.
_PRIMARY_TRUE_VALUES = {"TRUE", "YES"}


def validate_csv_headers(csv_text: str) -> list[dict[str, Any]]:
    """Block-level header validation: returns errors that should stop the
    upload before per-row validation runs. Empty list means headers are OK
    (or only have soft, non-blocking issues like extra columns).

    Catches two common authoring mistakes that would otherwise surface as
    thousands of confusing per-row errors:

    1. **Duplicate header names** — Python's ``dict(zip(headers, row))``
       silently keeps only the last value when two columns share a name,
       so the earlier column's data gets thrown away. Real example: a
       customer-supplied template named both the practitioner address
       state and the per-license state simply ``State``, and every
       license row appeared to have a blank License State.
    2. **Missing required headers** — if "First Name" / "Email" / etc.
       are absent or misspelled, every row's required-field validation
       fires and the user has no clue why.

    Each error is shaped like the per-row errors from
    ``validate_practitioner`` so the UI table can render them with no
    special-casing.
    """
    parsed = _parse_csv_rows(csv_text)
    if not parsed:
        return [{
            "row": 1,
            "field": "Header",
            "value": "",
            "message": "CSV is empty — no header row found.",
        }]

    # ``_clean_cell`` strips invisible Unicode (zero-width spaces and the
    # UTF-8 BOM) in addition to whitespace. Without this, Excel for
    # Windows' default ``CSV UTF-8 (Comma delimited)`` save format
    # prefixes the file with a BOM, the first header becomes
    # ``"﻿First Name"``, and the required-headers check below
    # emits the misleading "Required column 'First Name' is missing"
    # — which the admin reads while looking straight at a First Name
    # column. Same cleanup the per-row parser does for body cells.
    headers = [_clean_cell(h) for h in parsed[0]]
    errors: list[dict[str, Any]] = []

    # Duplicate header detection. Track the first column index per header
    # name; when we see a repeat, both columns are reported (the first so
    # the user can confirm which is the "real" one to keep, the second
    # so they know which to rename).
    seen_at: dict[str, int] = {}
    for col_index, header in enumerate(headers, start=1):
        if not header:
            continue
        if header in seen_at:
            errors.append({
                "row": 1,
                "field": "Header",
                "value": header,
                "message": (
                    f"Header '{header}' appears in column {seen_at[header]} "
                    f"and column {col_index}. Each column must have a unique "
                    f"name — rename one of them. (For per-license fields, "
                    f"prefix with 'License': e.g. 'License State' for the "
                    f"per-license state column.)"
                ),
            })
        else:
            seen_at[header] = col_index

    # Missing required headers. Skip this when duplicates already
    # exist — the duplicate fix may resolve the missing-header complaint.
    if not errors:
        present = set(headers)
        for required in REQUIRED_HEADERS:
            if required not in present:
                errors.append({
                    "row": 1,
                    "field": "Header",
                    "value": "",
                    "message": (
                        f"Required column '{required}' is missing from the "
                        f"header row. Download the template (top-right) for "
                        f"the expected schema."
                    ),
                })

    return errors


def _normalise_row(raw: dict[str, str]) -> dict[str, str]:
    """Convert a raw CSV row (header -> value) to internal keys.

    Strips leading/trailing whitespace and invisible Unicode chars
    (zero-width spaces, BOM) that commonly appear on paste-formatted cells.
    """
    return {
        _HEADER_MAP.get(k, k): _clean_cell(v)
        for k, v in raw.items()
        if k in _HEADER_MAP
    }


def _extract_license(row: dict[str, str]) -> dict[str, Any] | None:
    """Return a license dict from a normalised row, or None if empty.

    A license is "present" only when at least one *identifying* field is
    populated (type, name, license_state, number, issue_date, or
    expiration_date). ``primary_raw`` does NOT count — it carries the
    user's literal Primary cell (``FALSE``/``NO``/``TRUE``/``YES``/``""``)
    and a defensive ``Primary=FALSE`` on an otherwise-blank row would
    otherwise produce a phantom license dict with every other field empty.
    That phantom survives validation (every license rule short-circuits
    on empty ``type``) and then fails Canvas FHIR's regex check on the
    empty issuing-authority-short-name ``valueString``, surfacing as the
    opaque "License N: a required value is empty."
    """
    lic = {
        "type": row.get("license_type", ""),
        "name": row.get("license_name", ""),
        "license_state": row.get("license_state", ""),
        "number": row.get("license_number", ""),
        "issue_date": row.get("license_issue_date", ""),
        "expiration_date": row.get("license_expiration_date", ""),
        "primary_raw": row.get("license_primary", ""),
        "is_primary": row.get("license_primary", "").strip().upper() in _PRIMARY_TRUE_VALUES,
    }
    _IDENTIFYING_FIELDS = (
        "type", "name", "license_state", "number", "issue_date", "expiration_date",
    )
    if any((lic.get(k) or "").strip() for k in _IDENTIFYING_FIELDS):
        return lic
    return None


def parse_csv(csv_text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Parse CSV text into a list of merged practitioner records.

    Returns:
        (practitioners, parse_warnings)

        Each practitioner is a dict with:
            first_name, last_name, role, email, phone, dob,
            primary_practice_location, fax, npi,
            address_line1, address_line2, city, state, zip,
            licenses: list[dict],
            source_row_number: int   (for error reporting)
            raw_source_row: dict     (original row for continuation comparison)

        parse_warnings is a list of {"row": int, "message": str} dicts
        for rule-14 continuation-row field conflicts.
    """
    parsed_rows = _parse_csv_rows(csv_text)
    if not parsed_rows:
        return [], []
    # Strip invisibles (BOM, zero-width spaces) from headers in addition
    # to whitespace — Excel for Windows' default CSV UTF-8 save format
    # prefixes the file with a BOM, which would leave the first header
    # as ``"﻿First Name"`` and prevent _HEADER_MAP from recognising
    # it. validate_csv_headers does the same cleanup at its own header
    # read site; both paths must stay in sync.
    headers = [_clean_cell(h) for h in parsed_rows[0]]

    # Group rows by email (case-insensitive).
    #
    # Forward-fill behavior: if a row's Email is blank, it's treated as a
    # continuation of the most recent row that *did* have an email. This
    # matches the spreadsheet convention of leaving grouped-key cells empty
    # on continuation rows (e.g. one row per license, with demographics only
    # on the first row for each practitioner).
    #
    # The row's Email field is also back-filled so downstream validation and
    # result dicts see a non-empty email.
    groups: dict[str, list[tuple[int, dict[str, str]]]] = {}  # email -> [(row#, row)]
    last_email_key = ""
    last_email_original = ""
    for csv_row_index, row_values in enumerate(parsed_rows[1:], start=2):  # row 1 = header
        # Pad/truncate to header length so short rows don't drop columns
        padded = row_values + [""] * (len(headers) - len(row_values))
        raw_row = dict(zip(headers, padded[: len(headers)]))
        norm = _normalise_row(raw_row)
        email_raw = norm.get("email", "").strip()

        if email_raw:
            email_key = email_raw.lower()
            last_email_key = email_key
            last_email_original = email_raw
        elif last_email_key and not (
            norm.get("first_name", "").strip() or norm.get("last_name", "").strip()
        ):
            # Continuation row: inherit the group key and back-fill the
            # Email field on the row so required-field validation passes.
            # Continuation rows by convention have blank demographics — if
            # First/Last are populated, this is a separate practitioner
            # whose Email cell was accidentally blanked, not a continuation.
            email_key = last_email_key
            norm["email"] = last_email_original
        else:
            # No email and either (a) the first data row, or (b) a row with
            # populated First/Last that should not silently merge into the
            # previous practitioner. Synthetic key routes it to Rule 1
            # (Email required) as a hard error.
            #
            # Critical: also reset ``last_email_key`` so a subsequent
            # license-only continuation row (blank email + blank name) does
            # NOT latch onto the practitioner BEFORE this orphan — that
            # would silently attach the orphan's licenses to the wrong
            # record. The orphan acts as a barrier: anything after it that
            # would otherwise be a continuation becomes its own orphan
            # (also failing Rule 1) instead of leaking to the prior group.
            # This is the deeper layer of the Lykos misattribution pattern
            # Kevin Carey reported — the immediate-row case was patched
            # earlier; this fix closes the downstream-row case.
            email_key = f"__no_email_{csv_row_index}__"
            last_email_key = ""
            last_email_original = ""

        groups.setdefault(email_key, []).append((csv_row_index, norm))

    practitioners: list[dict[str, Any]] = []
    parse_warnings: list[dict[str, Any]] = []

    for _email_key, rows in groups.items():
        first_row_number, first_row = rows[0]

        # Build the merged practitioner from the first (defining) row
        raw_npi = first_row.get("npi", "").strip()
        practitioner: dict[str, Any] = {
            "first_name": first_row.get("first_name", ""),
            "last_name": first_row.get("last_name", ""),
            "role": first_row.get("role", ""),
            "email": first_row.get("email", ""),
            "phone": first_row.get("phone", ""),
            "dob": first_row.get("dob", ""),
            "primary_practice_location": first_row.get("primary_practice_location", ""),
            "fax": first_row.get("fax", ""),
            "npi": raw_npi if raw_npi else DEFAULT_NPI,
            "address_line1": first_row.get("address_line1", ""),
            "address_line2": first_row.get("address_line2", ""),
            "city": first_row.get("city", ""),
            "state": first_row.get("state", ""),
            "zip": first_row.get("zip", ""),
            "licenses": [],
            "source_row_number": first_row_number,
            "raw_source_row": first_row,
        }

        # Add license from the first row (if any)
        first_license = _extract_license(first_row)
        if first_license:
            practitioner["licenses"].append(first_license)

        # Merge continuation rows
        for cont_row_number, cont_row in rows[1:]:
            # Rule 14 check
            cont_warnings = validate_continuation_row(
                cont_row_number, first_row, cont_row
            )
            parse_warnings.extend(w.to_dict() for w in cont_warnings)

            # Add license from continuation row
            cont_license = _extract_license(cont_row)
            if cont_license:
                practitioner["licenses"].append(cont_license)

        practitioners.append(practitioner)

    return practitioners, parse_warnings


def build_qualification(lic: dict[str, str]) -> dict[str, Any]:
    """
    Map a parsed license dict to a FHIR qualification object matching
    Canvas's actual schema.

    Shape (empirically confirmed against a real Canvas instance — see
    `issuer.extension` payload of an existing practitioner's qualification):

        {
          "identifier": [{"system": "...", "value": "<license number>"}],
          "code": {"text": "<license type>"},
          "period": {"start": "...", "end": "..."},
          "issuer": {
            "display": "<license name OR license type as fallback>",
            "extension": [
              {"url": ".../issuing-authority-short-name", "valueString": "..."},
              {"url": ".../issuing-authority-state",       "valueString": "..."},
              {"url": ".../license-primary",              "valueBoolean": true|false}
            ]
          }
        }

    The issuing-authority-* extensions and the license-primary flag live
    *inside* ``issuer.extension`` — not at the top level of qualification.
    Canvas rejects with "qualification -> 0 -> issuer -> extension — must
    contain at least 1 item" if ``issuer.extension`` is missing or empty, so
    we always emit at least the license-primary boolean.

    Optional string fields (identifier.value, issuer.display,
    issuing-authority-short-name.valueString,
    issuing-authority-state.valueString) are omitted when their CSV value
    is blank — Canvas rejects empty ``valueString`` fields with the regex
    ``[ \\r\\n\\t\\S]+`` error.
    """
    code_text = canonicalize_license_type(lic.get("type", ""))
    name = (lic.get("name") or "").strip()
    license_state = (lic.get("license_state") or "").strip()
    number = (lic.get("number") or "").strip()

    # When the CSV's License Name is blank (legitimate for non-OTHER
    # license types), fall back to "{License Type} {License State}"
    # — e.g. "STATE AK" — so the resulting label distinguishes between
    # multiple state licenses on the same practitioner. Drops the state
    # piece when not applicable (e.g. DEA/CLIA/TAXONOMY → "DEA"). The
    # same fallback string is reused at merge-time on legacy records
    # whose long/short-name slots are empty (see
    # ``_license_name_fallback`` in api/bulk_upload_api.py).
    fallback_label = license_name_fallback(code_text, license_state)

    # Canvas's issuer.extension array is position-sensitive. Slot 0 MUST be
    # ``issuing-authority-short-name`` (and its valueString must be non-empty);
    # Canvas's validator rejects other URLs in that slot with
    # "must be set to: .../issuing-authority-short-name".
    issuer_extensions: list[dict[str, Any]] = [
        {
            "url": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-short-name",
            "valueString": name if name else fallback_label,
        }
    ]
    if license_state:
        issuer_extensions.append(
            {
                "url": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-state",
                "valueString": license_state,
            }
        )
    issuer_extensions.append(
        {
            "url": "http://schemas.canvasmedical.com/fhir/extensions/license-primary",
            "valueBoolean": lic.get("is_primary", False),
        }
    )

    qual: dict[str, Any] = {
        "code": {"text": code_text},
        "period": {},
        "issuer": {
            "display": name if name else fallback_label,
            "extension": issuer_extensions,
        },
    }

    if number:
        qual["identifier"] = [
            {
                "system": "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url",
                "value": number,
            }
        ]

    if lic.get("issue_date"):
        qual["period"]["start"] = to_fhir_date(lic["issue_date"])
    if lic.get("expiration_date"):
        qual["period"]["end"] = to_fhir_date(lic["expiration_date"])

    return qual


def build_fhir_practitioner(
    practitioner: dict[str, Any],
    location_map: dict[str, str],
    username_override: str | None = None,
) -> dict[str, Any]:
    """
    Build a FHIR Practitioner resource dict from a merged practitioner record.

    location_map: {location_name_lower -> "Location/<id>"}
    username_override: when provided, set as the
        ``practitioner-user-username`` extension on the resource. When None
        (the default), the extension is omitted and Canvas falls back to its
        own auto-generated username (``firstlast``). Callers retry with an
        explicit override on a username-collision 422.
    """
    resource: dict[str, Any] = {
        "resourceType": "Practitioner",
        "name": [
            {
                "use": "usual",
                "given": [practitioner["first_name"]],
                "family": practitioner["last_name"],
            }
        ],
        "telecom": [
            {
                "system": "phone",
                "value": practitioner["phone"],
                "use": "work",
                "rank": 1,
            },
            {
                "system": "email",
                "value": practitioner["email"],
                "use": "work",
                "rank": 1,
            },
        ],
        "birthDate": to_fhir_date(practitioner["dob"]),
        "extension": [
            {
                "url": "http://schemas.canvasmedical.com/fhir/extensions/roles",
                "extension": [
                    {
                        "url": "code",
                        "valueCoding": {
                            "system": "http://schemas.canvasmedical.com/fhir/roles",
                            "code": practitioner["role"],
                        },
                    }
                ],
            }
        ],
    }

    # practitioner-user-username — only emitted when the caller supplies
    # an override. By default Canvas auto-generates `firstlast`; the API
    # handler retries with build_username() (-> "first.last") on a
    # username-collision 422.
    if username_override:
        resource["extension"].append(
            {
                "url": "http://schemas.canvasmedical.com/fhir/extensions/practitioner-user-username",
                "valueString": username_override,
            }
        )

    # Fax
    if practitioner.get("fax"):
        resource["telecom"].append(
            {
                "system": "fax",
                "value": practitioner["fax"],
                "use": "work",
                "rank": 1,
            }
        )

    # NPI identifier
    if practitioner.get("npi"):
        resource["identifier"] = [
            {
                "system": "http://hl7.org/fhir/sid/us-npi",
                "value": practitioner["npi"],
            }
        ]

    # Primary practice location extension
    loc_name = practitioner.get("primary_practice_location", "").strip()
    if loc_name:
        loc_ref = location_map.get(loc_name.lower())
        if loc_ref:
            resource["extension"].append(
                {
                    "url": "http://schemas.canvasmedical.com/fhir/extensions/practitioner-primary-practice-location",
                    "valueReference": {
                        "reference": loc_ref,
                        "type": "Location",
                    },
                }
            )

    # Address (if any field is present)
    addr_fields = ["address_line1", "address_line2", "city", "state", "zip"]
    if any(practitioner.get(f) for f in addr_fields):
        # country is hard-coded to "US" (ISO 3166): Canvas's Staff UI emits
        # the same value, and the CSV template intentionally omits a Country
        # column. Without this default, Canvas stores country = "" on POST
        # and rows fail downstream lookups that expect a populated country.
        address: dict[str, Any] = {"use": "work", "type": "both", "country": "US"}
        lines = []
        if practitioner.get("address_line1"):
            lines.append(practitioner["address_line1"])
        if practitioner.get("address_line2"):
            lines.append(practitioner["address_line2"])
        if lines:
            address["line"] = lines
        if practitioner.get("city"):
            address["city"] = practitioner["city"]
        if practitioner.get("state"):
            address["state"] = practitioner["state"]
        if practitioner.get("zip"):
            address["postalCode"] = practitioner["zip"]
        resource["address"] = [address]

    # Qualifications (licenses)
    qualifications = [build_qualification(lic) for lic in practitioner.get("licenses", [])]
    if qualifications:
        resource["qualification"] = qualifications

    return resource


def diff_licenses(
    existing_qualifications: list[dict[str, Any]],
    incoming_licenses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], dict[str, Any]]]]:
    """Bucket incoming licenses against an existing Canvas record.

    Returns ``(new_licenses, renewals)``:
      - ``new_licenses``: incoming entries with no matching existing
        qualification by (canonicalised License Type, License Number).
      - ``renewals``: list of ``(incoming_lic, existing_qual)`` pairs where
        type+number match but ``period.start`` or ``period.end`` differ.
        Caller should update the existing qualification's period in place
        instead of creating a new one (avoids duplicate-number qualifications).

    Licenses where type+number match AND both dates are unchanged are
    omitted from both buckets — no action needed.

    Matching canonicalises both sides (e.g. CSV's "State license" and an
    older Canvas record's mixed casing both fold to "STATE"). Canvas's
    OTHER/SPI ``"License"`` downgrade is registered against both possible
    originals so re-uploading an OTHER row finds the existing record.
    """
    # Build existing index: (canonical_type, number) -> qualification
    existing_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for qual in existing_qualifications:
        code_text = qual.get("code", {}).get("text", "").strip()
        number = ""
        for ident in qual.get("identifier", []):
            if "issuing-authority-url" in ident.get("system", ""):
                number = ident.get("value", "").strip()
                break
        canonical = canonicalize_license_type(code_text)
        existing_by_key.setdefault((canonical, number), qual)
        # Canvas downgrades OTHER and SPI to the generic "License" label —
        # register both possible originals so an incoming OTHER/SPI re-upload
        # matches the existing record.
        if canonical == "License":
            existing_by_key.setdefault(("OTHER", number), qual)
            existing_by_key.setdefault(("SPI", number), qual)

    new_licenses: list[dict[str, Any]] = []
    renewals: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for lic in incoming_licenses:
        key = (
            canonicalize_license_type(lic.get("type", "").strip()),
            lic.get("number", "").strip(),
        )
        existing = existing_by_key.get(key)
        if existing is None:
            new_licenses.append(lic)
            continue
        period = existing.get("period") or {}
        existing_start = (period.get("start") or "").strip()
        existing_end = (period.get("end") or "").strip()
        incoming_start = to_fhir_date((lic.get("issue_date") or "").strip())
        incoming_end = to_fhir_date((lic.get("expiration_date") or "").strip())
        # Only count as a renewal when at least one incoming date is provided
        # AND it actually differs from what's on Canvas. CSV blanks shouldn't
        # erase Canvas's existing dates.
        date_changed = False
        if incoming_start and incoming_start != existing_start:
            date_changed = True
        if incoming_end and incoming_end != existing_end:
            date_changed = True
        if date_changed:
            renewals.append((lic, existing))

    return new_licenses, renewals


TEMPLATE_CSV = """\
First Name,Last Name,Role,Primary Practice Location,Email,Phone,Fax,NPI,DOB,Address Line 1,Address Line 2,City,State,Zip,License Type,License Name,License State,License Number,License Issue Date,License Expiration Date,Primary
Jane,Smith,MD,Main Street Clinic,jane.smith@example.com,5555550100,5555550101,1111155556,03-15-1980,123 Main St,Suite 200,New York,NY,10001,STATE,NY Medical Board,NY,MD12345,01-01-2020,01-01-2026,Yes
,,,,,,,,,,,,,,DEA,,,AS1234567,06-01-2021,06-01-2027,No
John,Doe,RN,Westside Clinic,john.doe@example.com,5555550200,,,07-22-1975,456 Oak Ave,,Los Angeles,CA,90001,STATE,CA Board of Nursing,CA,RN67890,05-10-2019,05-10-2025,TRUE
"""
