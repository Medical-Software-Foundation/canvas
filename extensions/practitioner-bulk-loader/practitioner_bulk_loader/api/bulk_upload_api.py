"""
SimpleAPI endpoints for the Practitioner Bulk Loader.

Endpoints:
  GET  /bulk-upload/template.csv        - Download CSV template
  POST /bulk-upload/parse-and-validate  - Parse CSV, validate, detect duplicates
  POST /bulk-upload/create-practitioners - Execute creates/merges/skips
"""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any

import requests
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.v1.data.staff import Staff
from django.db import DatabaseError
from logger import log

from practitioner_bulk_loader.utils.csv_parser import (
    DEFAULT_NPI,
    TEMPLATE_CSV,
    build_fhir_practitioner,
    build_qualification,
    build_username,
    diff_licenses,
    license_name_fallback,
    parse_csv,
    validate_csv_headers,
)
from practitioner_bulk_loader.utils.fhir_client import (
    MissingSecretError,
    create_practitioner,
    get_location_map,
    make_fhir_client,
    read_practitioner,
    replace_practitioner,
)
from practitioner_bulk_loader.utils.validation import to_fhir_date, validate_practitioner

_STAFF_ROLES_HELP_URL = (
    "https://canvas-medical.help.usepylon.com/articles/6649603926-staff-roles"
)


_ADDRESS_FIELD_MAP: dict[str, str] = {
    "line1": "address_line1",
    "line2": "address_line2",
    "city": "city",
    "state": "state",
    "zip": "zip",
}


def _expand_address_for_fhir(prac: dict[str, Any]) -> None:
    """Mirror nested ``address: {line1, line2, ...}`` (the shape the UI sends
    on Import) back onto the flat ``address_line1`` / ``city`` / etc. keys
    that ``build_fhir_practitioner`` reads from. Mutates ``prac`` in place.
    Only fills flat keys that are currently empty — never overwrites a real
    flat value with the nested one (defensive, in case both shapes are
    ever supplied at once).
    """
    nested = prac.get("address")
    if not isinstance(nested, dict):
        return
    for nested_key, flat_key in _ADDRESS_FIELD_MAP.items():
        if not (prac.get(flat_key) or "").strip():
            prac[flat_key] = nested.get(nested_key, "")


def _bare_staff_key(practitioner_id: str) -> str:
    """Strip the FHIR ``Practitioner/`` prefix to get the bare 32-char Staff
    key. We keep ``existing_id`` in the full ``Practitioner/{key}`` form
    internally because the FHIR write helpers (read_practitioner,
    replace_practitioner) accept either, but the UI/results ``staff_key``
    field surfaces the bare key — that's what staff admins paste into
    Canvas's Staff URLs."""
    return (practitioner_id or "").replace("Practitioner/", "")


def _build_staff_directory() -> dict[str, Any]:
    """Build duplicate-detection indexes by querying Canvas's Staff ORM directly.

    Returns a dict with four lookup tables:
      - ``by_email``: ``{email_lower: compact_staff}``
      - ``by_npi``: ``{npi: compact_staff}`` — placeholder NPI excluded
      - ``by_name_dob``: ``{(first_lower, last_lower, dob_iso): compact_staff}``
      - ``by_name``: ``{(first_lower, last_lower): [compact_staff, ...]}``

    Each ``compact_staff`` is a small dict with ``id``, ``first_name``,
    ``last_name``, ``birth_date`` — enough to render the preview row and
    pass an ``existing_id`` to the merge endpoint.

    Why query Staff directly instead of FHIR Practitioner: Canvas's Staff
    table is the authoritative source for its own duplicate-name uniqueness
    check (the rule that produces 422/502 errors on POST /Practitioner). It
    also catches "phantom" Staff records — rows that exist on the Staff
    table without a corresponding Practitioner FHIR resource (a known Canvas
    consistency issue). FHIR-only detection misses those phantoms.
    """
    by_email: dict[str, dict[str, Any]] = {}
    by_npi: dict[str, dict[str, Any]] = {}
    by_name_dob: dict[tuple[str, str, str], dict[str, Any]] = {}
    by_name: dict[tuple[str, str], list[dict[str, Any]]] = {}

    # ``.prefetch_related("telecom")`` collapses the per-staff
    # StaffContactPoint lookup (used inside the loop) from N+1 queries
    # into one. ``.only(...)`` narrows the column fetch to the five
    # fields the indexer reads. ``.iterator(chunk_size=200)`` streams
    # rows so a large Staff table doesn't materialize fully in memory.
    queryset = (
        Staff.objects
        .filter(active=True)
        .only("id", "first_name", "last_name", "birth_date", "npi_number")
        .prefetch_related("telecom")
    )
    for staff in queryset.iterator(chunk_size=200):
        first_lower = (staff.first_name or "").strip().lower()
        last_lower = (staff.last_name or "").strip().lower()
        dob_iso = staff.birth_date.isoformat() if staff.birth_date else ""
        npi = (staff.npi_number or "").strip()

        compact: dict[str, Any] = {
            "id": staff.id,
            "first_name": staff.first_name or "",
            "last_name": staff.last_name or "",
            "birth_date": dob_iso,
        }

        # NPI tier — skip placeholder so blank-NPI staff don't all collide.
        if npi and npi != DEFAULT_NPI and npi not in by_npi:
            by_npi[npi] = compact

        if first_lower and last_lower:
            by_name.setdefault((first_lower, last_lower), []).append(compact)
            if dob_iso:
                key = (first_lower, last_lower, dob_iso)
                if key not in by_name_dob:
                    by_name_dob[key] = compact

        # Email tier — telecom is a reverse FK to StaffContactPoint.
        for cp in staff.telecom.all():
            if (getattr(cp, "system", "") or "").lower() == "email":
                value = (getattr(cp, "value", "") or "").strip()
                if value:
                    email_key = value.lower()
                    if email_key not in by_email:
                        by_email[email_key] = compact

    return {
        "by_email": by_email,
        "by_npi": by_npi,
        "by_name_dob": by_name_dob,
        "by_name": by_name,
    }


_ISSUING_AUTHORITY_URL = (
    "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-url"
)
_ISSUING_AUTHORITY_SHORT_NAME_URL = (
    "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-short-name"
)
_ISSUING_AUTHORITY_STATE_URL = (
    "http://schemas.canvasmedical.com/fhir/extensions/issuing-authority-state"
)

_NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"


def _normalize_existing_qualification_identifiers(
    qualification: dict[str, Any],
) -> dict[str, Any]:
    """Sanitise an existing qualification's ``identifier`` array before PUT.

    Two transformations:
    1. Rewrite ``identifier[i].system`` to the canonical issuing-authority-url
       URL when blank or non-canonical. Legacy Canvas records often have
       this slot empty (the UI's "Issuing authority url" field is optional).
       Canvas's current PUT validator demands the canonical URL, so a
       GET-modify-PUT roundtrip on legacy data fails with "License N:
       System: must be set to: …" without this rewrite.
    2. Drop any identifier entry whose ``value`` is blank. An identifier
       with no value is degenerate data — there's nothing to identify —
       and Canvas's PUT validator rejects empty values with "License N:
       License Number is required." Dropping the empty identifier (rather
       than auto-filling a placeholder) preserves the qualification itself
       (code, period, issuer all intact); only the meaningless identifier
       slot is removed.

    Other required-but-blank fields (License Type, License Name, etc.) are
    left alone — those would be auto-filling actual identifying data and
    the user has chosen to surface them as per-row errors instead.
    """
    identifiers = qualification.get("identifier") or []
    if not identifiers:
        return qualification

    fixed_identifiers: list[dict[str, Any]] = []
    for ident in identifiers:
        if not (ident.get("value") or "").strip():
            # Drop — degenerate data, can't auto-fill the value.
            continue
        if (ident.get("system") or "") != _ISSUING_AUTHORITY_URL:
            ident = {**ident, "system": _ISSUING_AUTHORITY_URL}
        fixed_identifiers.append(ident)

    if fixed_identifiers == identifiers:
        return qualification
    if not fixed_identifiers:
        # Every identifier was empty-valued and dropped; remove the field
        # entirely rather than PUTting an empty array (some validators
        # treat empty arrays differently from absent fields).
        cleaned = {**qualification}
        cleaned.pop("identifier", None)
        return cleaned
    return {**qualification, "identifier": fixed_identifiers}


def _normalize_existing_qualification_license_name(
    qualification: dict[str, Any],
) -> dict[str, Any]:
    """Fill blank License Name slots on an existing qualification before PUT.

    Canvas's PUT validator rejects qualifications whose ``issuer.display``
    or ``issuer.extension[short-name].valueString`` is blank/missing, but
    the Canvas admin UI lets staff save licenses with both "Issuing
    authority long name" and "Issuing authority short name" empty. The
    GET-modify-PUT loop fails until those slots are populated.

    Three repair shapes are handled:

    1. ``issuer.display`` blank → fill with "{License Type} {License State}"
       (e.g. "STATE AK"), drawn from data already on the qualification.
    2. short-name extension present but its ``valueString`` blank → fill
       with the same fallback.
    3. **short-name extension missing entirely** → insert one at slot 0
       (Canvas's PUT validator requires slot 0 to be the short-name URL,
       and rejects with "License N: Url: must be set to: …short-name").
       The inserted ``valueString`` prefers an already-populated
       ``issuer.display`` (preserves the admin's chosen label like
       "Texas Medical Board") and falls back to the systematic
       "{License Type} {License State}" form when display is also blank.
       Other extensions (state, license-primary) keep their relative
       order after the inserted short-name slot.

    Drawn from data already present on the qualification — never
    invented. If neither ``issuer.display``, ``code.text``, nor the state
    extension yield anything usable, the slot is left untouched and the
    error still surfaces, prompting a manual fix.
    """
    code_text = (qualification.get("code", {}) or {}).get("text", "") or ""
    issuer = qualification.get("issuer") or {}
    extensions = issuer.get("extension") or []

    # Pull the state extension's value to compose the systematic fallback.
    state_code = ""
    for ext in extensions:
        if ext.get("url") == _ISSUING_AUTHORITY_STATE_URL:
            state_code = (ext.get("valueString") or "").strip()
            break

    fallback = license_name_fallback(code_text, state_code)
    display = (issuer.get("display") or "").strip()
    # Prefer existing display for the inserted short-name slot — it's the
    # admin's chosen label. Fall back to systematic "{TYPE} {STATE}" only
    # when display is blank.
    short_name_value = display or fallback
    if not short_name_value:
        return qualification  # nothing usable to fall back to

    needs_change = False
    new_issuer: dict[str, Any] = dict(issuer)

    # 1. issuer.display
    if not display:
        new_issuer["display"] = fallback
        needs_change = True

    # 2 & 3. issuer.extension array
    has_short_name = any(
        ext.get("url") == _ISSUING_AUTHORITY_SHORT_NAME_URL for ext in extensions
    )
    fixed_extensions: list[dict[str, Any]] = []
    for ext in extensions:
        if ext.get("url") == _ISSUING_AUTHORITY_SHORT_NAME_URL:
            current = (ext.get("valueString") or "").strip()
            if not current:
                ext = {**ext, "valueString": short_name_value}
                needs_change = True
        fixed_extensions.append(ext)

    if not has_short_name:
        # Insert short-name extension at slot 0 — Canvas's PUT validator
        # is strict about position here.
        fixed_extensions.insert(0, {
            "url": _ISSUING_AUTHORITY_SHORT_NAME_URL,
            "valueString": short_name_value,
        })
        needs_change = True

    if not needs_change:
        return qualification

    new_issuer["extension"] = fixed_extensions
    return {**qualification, "issuer": new_issuer}


def _normalize_existing_practitioner_identifier(
    existing_resource: dict[str, Any],
    csv_npi: str,
) -> None:
    """Fill or drop blank top-level Practitioner ``identifier`` entries.

    Mutates ``existing_resource`` in place. The Practitioner-level
    ``identifier`` array on Canvas is the NPI slot. Legacy customer
    records sometimes have an NPI identifier with empty ``value`` (the
    Canvas admin UI accepted blanks at save time), and Canvas's current
    PUT validator rejects identifier entries with empty values — surfaces
    as a bare "NPI is required." error blocking otherwise-fine merges.

    Resolution:
      * If the NPI value is blank and the CSV row supplies an NPI (real or
        the parser's placeholder when CSV was blank), write it into the
        existing entry. The CSV is the only legitimate source of an NPI;
        we never invent one beyond the parser's already-substituted value.
      * If the NPI value is blank and the CSV also has no usable value,
        drop the empty identifier entry rather than ship blank data.
      * Any non-NPI top-level identifier with blank value is dropped
        (degenerate data, no caller to consult).
    """
    csv_npi_clean = (csv_npi or "").strip()
    identifiers = existing_resource.get("identifier") or []

    if not identifiers:
        # No identifier slot at all — synthesise one so the merged record
        # always has an NPI (Canvas requires every Practitioner to have
        # one; the parser substitutes DEFAULT_NPI when the CSV row is
        # blank, so csv_npi_clean is non-empty in practice).
        if csv_npi_clean:
            existing_resource["identifier"] = [
                {"system": _NPI_SYSTEM, "value": csv_npi_clean}
            ]
        return

    fixed: list[dict[str, Any]] = []
    for ident in identifiers:
        value = (ident.get("value") or "").strip()
        if value:
            fixed.append(ident)
            continue
        # Empty value — handle by system.
        if ident.get("system") == _NPI_SYSTEM and csv_npi_clean:
            fixed.append({**ident, "value": csv_npi_clean})
        # else: drop the empty entry entirely.

    if fixed:
        existing_resource["identifier"] = fixed
    else:
        existing_resource.pop("identifier", None)


_DIGIT_ONLY_TELECOM_SYSTEMS = ("phone", "fax", "pager")


def _normalize_existing_telecom(telecom: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitise an existing telecom list before PUT.

    Two transformations:

    1. **Rank normalisation per system.** For each system (email / phone
       / fax / etc.), exactly one entry must have ``rank=1`` and the rest
       must not — Canvas's PUT validator rejects with *"must contain
       exactly one ContactPoint where system=email and rank=1"*
       otherwise. We pick a canonical rank-1 entry (preferring an
       existing rank-1, otherwise the first occurrence of that system)
       and force every other entry of the same system to ``rank=2``.

    2. **Strip non-digit characters from phone/fax/pager values.** The
       Canvas admin UI accepts formatted numbers like ``(555) 555-0100``
       on save; the FHIR PUT validator rejects them with *"Value: must
       only contain digits"*. Stripping non-digits in place preserves
       the actual phone number — it just removes formatting. If the
       value becomes empty after stripping (e.g. it was ``"N/A"``), the
       entry is dropped.

    No contact values are auto-filled — if a customer's record has a
    legitimate phone number, it stays; only formatting characters get
    removed.
    """
    if not telecom:
        return telecom

    changed = False

    # Pass 0: strip non-digits from phone/fax/pager values; drop entries
    # that become empty after stripping (entry was non-digit text only).
    stripped: list[dict[str, Any]] = []
    for entry in telecom:
        system = (entry.get("system") or "").lower()
        if system in _DIGIT_ONLY_TELECOM_SYSTEMS:
            value = entry.get("value") or ""
            digits_only = re.sub(r"\D", "", value)
            if digits_only != value:
                changed = True
                if not digits_only:
                    continue  # drop entry that held only non-digits
                entry = {**entry, "value": digits_only}
        stripped.append(entry)

    # If everything was dropped, nothing to rank-normalise.
    if not stripped:
        return stripped

    # Pass 1: pick the index that should hold rank=1 per system.
    # Prefer entries that are already rank=1; otherwise the first
    # occurrence of that system in the list.
    rank1_index_per_system: dict[str, int] = {}
    for i, entry in enumerate(stripped):
        system = entry.get("system") or ""
        if system in rank1_index_per_system:
            continue
        if entry.get("rank") == 1:
            rank1_index_per_system[system] = i
    # Backfill systems that had no rank-1 entry — promote the first.
    for i, entry in enumerate(stripped):
        system = entry.get("system") or ""
        if system not in rank1_index_per_system:
            rank1_index_per_system[system] = i

    # Pass 2: write the normalised list. Only rewrite ranks; preserve
    # all other fields exactly.
    fixed: list[dict[str, Any]] = []
    for i, entry in enumerate(stripped):
        system = entry.get("system") or ""
        target_rank = 1 if i == rank1_index_per_system[system] else 2
        if entry.get("rank") != target_rank:
            entry = {**entry, "rank": target_rank}
            changed = True
        fixed.append(entry)

    return fixed if changed else telecom


_FIELD_CONFLICT_PAIRS: tuple[tuple[str, str, bool], ...] = (
    # (csv_key, ui_label, case_insensitive)
    ("first_name", "First Name", True),
    ("last_name", "Last Name", True),
    ("dob", "DOB", False),
    ("email", "Email", True),
    ("phone", "Phone", False),
    ("fax", "Fax", False),
    ("npi", "NPI", False),
    ("address_line1", "Address Line 1", False),
    ("address_line2", "Address Line 2", False),
    ("city", "City", False),
    ("state", "State", False),
    ("zip", "Zip", False),
)


def _extract_existing_field_values(
    existing_resource: dict[str, Any],
) -> dict[str, str]:
    """Pull the comparable scalar fields out of an existing Practitioner.

    Used to detect silent mismatches: any field where the CSV value differs
    from what Canvas already has, the merge will not overwrite. Surfacing
    the difference in the preview lets the staff admin avoid the trap of
    assuming the CSV's values were applied.
    """
    name = (existing_resource.get("name") or [{}])[0]
    given_list = name.get("given") or []
    first = (given_list[0] if given_list else "") or ""
    family = name.get("family") or ""

    def _primary_value(system: str) -> str:
        candidates = [
            t for t in (existing_resource.get("telecom") or [])
            if (t.get("system") or "").lower() == system
        ]
        if not candidates:
            return ""
        rank1 = [t for t in candidates if t.get("rank") == 1]
        return ((rank1[0] if rank1 else candidates[0]).get("value") or "")

    npi = ""
    for ident in existing_resource.get("identifier") or []:
        if ident.get("system") == _NPI_SYSTEM:
            npi = (ident.get("value") or "").strip()
            break

    address = (existing_resource.get("address") or [{}])[0]
    line = address.get("line") or []
    line1 = (line[0] if line else "") or ""
    line2 = (line[1] if len(line) > 1 else "") or ""

    # Strip non-digit characters from phone/fax. Canvas's admin UI saves
    # formatted values like ``(555) 555-0100`` (also documented in
    # ``_normalize_existing_telecom`` for the PUT-time strip), but Rule 3
    # forces the CSV side to be digits-only. Comparing the two without
    # normalisation produces phantom Phone/Fax conflicts on every record
    # that was entered through the Canvas admin UI — blocking imports
    # behind a per-row ack flow for no real difference.
    return {
        "first_name": first.strip(),
        "last_name": family.strip(),
        "dob": (existing_resource.get("birthDate") or "").strip(),
        "email": _primary_value("email").strip(),
        "phone": re.sub(r"\D", "", _primary_value("phone")),
        "fax": re.sub(r"\D", "", _primary_value("fax")),
        "npi": npi,
        "address_line1": line1.strip(),
        "address_line2": line2.strip(),
        "city": (address.get("city") or "").strip(),
        "state": (address.get("state") or "").strip(),
        "zip": (address.get("postalCode") or "").strip(),
    }


def _compute_field_conflicts(
    prac: dict[str, Any],
    existing: dict[str, str],
) -> list[dict[str, Any]]:
    """Return list of fields where both sides have populated values that
    differ. These are the silent surprises — the merge keeps Canvas's
    value, but a staff admin might assume the CSV's value is applied.

    Fields where only one side has a value are not reported here:
      * existing-blank + CSV-populated: handled by the fill-missing
        normalizers (address, NPI) or by the field being non-mergeable.
        Either way, the preview communicates the outcome through other
        signals (the per-row badge for licenses, the defaulted-NPI banner).
      * existing-populated + CSV-blank: CSV has nothing to say, no
        surprise.

    DOB strings are normalised to ISO before comparison so 03-15-1980 and
    1980-03-15 don't false-positive as different.
    """
    conflicts: list[dict[str, Any]] = []

    csv_npi = (prac.get("npi") or "").strip()
    if csv_npi == DEFAULT_NPI:
        csv_npi = ""

    csv_values = {
        "first_name": (prac.get("first_name") or "").strip(),
        "last_name": (prac.get("last_name") or "").strip(),
        "dob": to_fhir_date((prac.get("dob") or "").strip()) if prac.get("dob") else "",
        "email": (prac.get("email") or "").strip(),
        "phone": (prac.get("phone") or "").strip(),
        "fax": (prac.get("fax") or "").strip(),
        "npi": csv_npi,
        "address_line1": (prac.get("address_line1") or "").strip(),
        "address_line2": (prac.get("address_line2") or "").strip(),
        "city": (prac.get("city") or "").strip(),
        "state": (prac.get("state") or "").strip(),
        "zip": (prac.get("zip") or "").strip(),
    }

    for csv_key, ui_label, case_insensitive in _FIELD_CONFLICT_PAIRS:
        csv_val = csv_values.get(csv_key, "")
        existing_val = (existing.get(csv_key) or "").strip()
        # Symmetric placeholder handling for NPI. The CSV-side zeroing
        # above covers "CSV blank, Canvas real" (asymmetric, surfaced
        # separately below); this covers the inverse "Canvas blank /
        # placeholder, CSV real" — without it the conflict loop would
        # treat the placeholder as a real existing value and emit a
        # phantom NPI conflict on every record that was originally
        # loaded with a blank NPI.
        if csv_key == "npi" and existing_val == DEFAULT_NPI:
            existing_val = ""
        # Strip non-digit characters from phone/fax before comparing —
        # CSV is digits-only by Rule 3 but Canvas admin UI saves
        # formatted values like "(555) 555-0100". Without this every
        # admin-UI-entered phone would produce a phantom conflict.
        if csv_key in ("phone", "fax"):
            csv_val = re.sub(r"\D", "", csv_val)
            existing_val = re.sub(r"\D", "", existing_val)
        if not csv_val or not existing_val:
            continue
        if case_insensitive:
            if csv_val.lower() == existing_val.lower():
                continue
        elif csv_val == existing_val:
            continue
        conflicts.append({
            "field": ui_label,
            "csv": csv_val,
            "existing": existing_val,
        })

    # Asymmetric NPI case: Canvas already has a real NPI but the CSV row
    # leaves it blank (the placeholder ``DEFAULT_NPI`` is zeroed above so
    # csv_values["npi"] is empty here). Surface this as a conflict so the
    # diff panel discloses what Canvas has — admins picking 'Replace
    # record' need to know they're keeping the existing NPI (the write
    # path also guards against clobbering, so existing is preserved
    # regardless of action).
    #
    # Skip when Canvas's stored NPI is itself the placeholder — that means
    # the existing record was originally loaded with a blank NPI too, so
    # both sides are effectively "no NPI on file" and there is no real
    # asymmetry to disclose. Surfacing a conflict here would be noise.
    if not csv_values["npi"]:
        existing_npi = (existing.get("npi") or "").strip()
        if existing_npi and existing_npi != DEFAULT_NPI:
            conflicts.append({
                "field": "NPI",
                "csv": "",
                "existing": existing_npi,
            })

    return conflicts


def _normalize_existing_address(
    existing_resource: dict[str, Any],
    prac: dict[str, Any],
) -> None:
    """Fill missing address fields on an existing Practitioner from CSV data.

    Mutates ``existing_resource`` in place. Policy mirrors the NPI handling
    in ``_normalize_existing_practitioner_identifier``: fill missing values,
    don't overwrite populated ones. If the existing record has no address at
    all (the legacy-record case: created elsewhere with no demographics), build
    a fresh address block from CSV. If existing has a partial address, fill
    only the blank fields so a state/zip the CSV provides reaches Canvas
    instead of being silently dropped.
    """
    csv_line1 = prac.get("address_line1", "").strip()
    csv_line2 = prac.get("address_line2", "").strip()
    csv_city = prac.get("city", "").strip()
    csv_state = prac.get("state", "").strip()
    csv_zip = prac.get("zip", "").strip()
    has_csv_address = any((csv_line1, csv_line2, csv_city, csv_state, csv_zip))
    if not has_csv_address:
        return

    existing_addresses = existing_resource.get("address") or []
    if not existing_addresses:
        addr: dict[str, Any] = {"use": "work", "type": "both", "country": "US"}
        lines = [v for v in (csv_line1, csv_line2) if v]
        if lines:
            addr["line"] = lines
        if csv_city:
            addr["city"] = csv_city
        if csv_state:
            addr["state"] = csv_state
        if csv_zip:
            addr["postalCode"] = csv_zip
        existing_resource["address"] = [addr]
        return

    addr = dict(existing_addresses[0])
    # Treat the line array as a unit: never mix-and-match a CSV line2 with
    # an existing line1 (different building). Only write CSV lines when
    # existing has no line at all.
    existing_lines = [ln for ln in (addr.get("line") or []) if (ln or "").strip()]
    if not existing_lines:
        csv_lines = [v for v in (csv_line1, csv_line2) if v]
        if csv_lines:
            addr["line"] = csv_lines
    if csv_city and not (addr.get("city") or "").strip():
        addr["city"] = csv_city
    if csv_state and not (addr.get("state") or "").strip():
        addr["state"] = csv_state
    if csv_zip and not (addr.get("postalCode") or "").strip():
        addr["postalCode"] = csv_zip
    if not (addr.get("country") or "").strip():
        addr["country"] = "US"

    existing_addresses[0] = addr
    existing_resource["address"] = existing_addresses


def _apply_csv_to_existing(
    existing_resource: dict[str, Any],
    prac: dict[str, Any],
    address_mode: str = "overwrite",
    scope: str = "all",
) -> None:
    """Overwrite an existing Practitioner's fields with CSV values.

    Triggered when the staff admin picks 'Replace record', 'Replace
    address only', or 'Add address as additional' on an existing-matched
    row. CSV is treated as the source of truth for the in-scope fields.

    Mutates ``existing_resource`` in place. Email is never touched (FHIR
    spec rejects email changes on PUT).

    ``scope``:
      ``"all"`` (default) — overwrite name, DOB, phone, fax, NPI, and
      address. Used by 'Replace record'.
      ``"address_only"`` — overwrite ONLY the address; leave name, DOB,
      telecom, and NPI alone. Used by 'Replace address only' and
      'Add address as additional'.

    ``address_mode`` (only meaningful when address is being modified):
      ``"overwrite"`` (default) — replace existing.address[0] with CSV
      ``"additional"`` — append the CSV address as a new entry; existing
      primary stays. Useful when both addresses are real (e.g. work +
      satellite clinic) and the admin doesn't want to lose the existing.

    Field-fill normalizers (`_normalize_existing_address`, etc.) are
    designed to be no-ops when the target field is already populated, so
    running them after this function is harmless — they fill anything
    this function didn't (e.g. country defaults).
    """
    if scope == "all":
        _apply_csv_non_address(existing_resource, prac)
    _apply_csv_address(existing_resource, prac, address_mode)


def _apply_csv_non_address(
    existing_resource: dict[str, Any],
    prac: dict[str, Any],
) -> None:
    """Overwrite name, DOB, telecom (phone/fax), and NPI on existing."""
    first = (prac.get("first_name") or "").strip()
    last = (prac.get("last_name") or "").strip()
    if first or last:
        names = list(existing_resource.get("name") or [{}])
        n = dict(names[0])
        if last:
            n["family"] = last
        if first:
            given = list(n.get("given") or [])
            if given:
                given[0] = first
            else:
                given = [first]
            n["given"] = given
        names[0] = n
        existing_resource["name"] = names

    dob = (prac.get("dob") or "").strip()
    if dob:
        existing_resource["birthDate"] = to_fhir_date(dob)

    telecom = list(existing_resource.get("telecom") or [])

    def _upsert_telecom(system: str, csv_value: str) -> None:
        if not csv_value:
            return
        candidates = [
            i for i, t in enumerate(telecom)
            if (t.get("system") or "").lower() == system
        ]
        if not candidates:
            telecom.append(
                {"system": system, "value": csv_value, "rank": 1, "use": "work"}
            )
            return
        rank1 = [i for i in candidates if telecom[i].get("rank") == 1]
        target = rank1[0] if rank1 else candidates[0]
        telecom[target] = {**telecom[target], "value": csv_value}

    _upsert_telecom("phone", (prac.get("phone") or "").strip())
    _upsert_telecom("fax", (prac.get("fax") or "").strip())
    if telecom:
        existing_resource["telecom"] = telecom

    csv_npi = (prac.get("npi") or "").strip()
    # Never write the placeholder NPI over an existing real value. csv_parser
    # substitutes ``DEFAULT_NPI`` for blank CSV cells, and without this guard
    # ``merge_apply`` would silently clobber a real existing NPI (e.g. a
    # legit 1234567890 on Canvas) with "1111155556" — destroying real data.
    # The read-side dedup index and conflict-display logic already filter
    # the placeholder elsewhere; the write path was the asymmetric outlier.
    if csv_npi and csv_npi != DEFAULT_NPI:
        identifiers = list(existing_resource.get("identifier") or [])
        npi_idx = next(
            (i for i, ident in enumerate(identifiers)
             if ident.get("system") == _NPI_SYSTEM),
            -1,
        )
        if npi_idx >= 0:
            identifiers[npi_idx] = {**identifiers[npi_idx], "value": csv_npi}
        else:
            identifiers.append({"system": _NPI_SYSTEM, "value": csv_npi})
        existing_resource["identifier"] = identifiers


def _apply_csv_address(
    existing_resource: dict[str, Any],
    prac: dict[str, Any],
    address_mode: str = "overwrite",
) -> None:
    """Write the CSV address onto an existing Practitioner.

    ``address_mode``:
      ``"overwrite"`` — merge CSV values onto ``existing.address[0]``,
      preserving slots the CSV is blank on (Line 2 / apartment numbers,
      the address's ``id``, district, extensions, etc.). The CSV is the
      source of truth for the slots it carries; everything else stays.
      ``"additional"`` — append the CSV address as a new entry; this
      function on its own leaves the existing primary untouched.

    **Caller note (additional mode):** ``_do_merge`` calls this function
    and then runs ``_normalize_existing_address`` two steps later, which
    fills blank slots on the existing primary from the CSV. So the
    merge flow as a whole *does* modify the primary in the
    partial-primary case — blank-on-Canvas fields get the CSV value,
    populated slots are still untouched. The diff panel hides this
    transparently because ``_compute_field_conflicts`` filters out
    conflicts where either side is blank, so admins never see a
    misleading "primary kept" label on a slot that's actually being
    filled. The README's "Add address as additional" section documents
    this contract; future callers should not treat the docstring above
    in isolation as the merge flow's whole story.

    Why merge instead of wholesale replace on overwrite: the CSV schema
    only carries Line 1 / Line 2 / City / State / Zip, but Canvas may
    have additional fields on the existing address (most importantly the
    record ``id``, but also custom extensions or address-level metadata).
    A wholesale replace silently dropped Line 2 (apartment numbers) on
    every row whose CSV happened to leave that column blank, and would
    have orphaned the existing address record per the Canvas FHIR docs
    (omitting the ``id`` on PUT creates a new record rather than
    updating the existing one).
    """
    csv_line1 = (prac.get("address_line1") or "").strip()
    csv_line2 = (prac.get("address_line2") or "").strip()
    csv_city = (prac.get("city") or "").strip()
    csv_state = (prac.get("state") or "").strip()
    csv_zip = (prac.get("zip") or "").strip()
    has_csv_address = any((csv_line1, csv_line2, csv_city, csv_state, csv_zip))
    if not has_csv_address:
        return

    addresses = list(existing_resource.get("address") or [])

    if address_mode == "additional" and addresses:
        # New entry — no existing slots to preserve.
        new_addr: dict[str, Any] = {"use": "work", "type": "both", "country": "US"}
        lines = [v for v in (csv_line1, csv_line2) if v]
        if lines:
            new_addr["line"] = lines
        if csv_city:
            new_addr["city"] = csv_city
        if csv_state:
            new_addr["state"] = csv_state
        if csv_zip:
            new_addr["postalCode"] = csv_zip
        addresses.append(new_addr)
    elif addresses:
        # Overwrite mode with an existing primary: merge CSV onto a copy
        # of addresses[0] so non-CSV fields (id, extension, etc.) survive.
        merged = dict(addresses[0])
        merged.setdefault("use", "work")
        merged.setdefault("type", "both")
        merged.setdefault("country", "US")
        # Line array — treat as a unit (never mix CSV Line 2 with existing
        # Line 1). Only rewrite when CSV supplied any line value.
        csv_lines = [v for v in (csv_line1, csv_line2) if v]
        if csv_lines:
            merged["line"] = csv_lines
        if csv_city:
            merged["city"] = csv_city
        if csv_state:
            merged["state"] = csv_state
        if csv_zip:
            merged["postalCode"] = csv_zip
        addresses[0] = merged
    else:
        # No existing addresses — build from CSV (no slots to preserve).
        new_addr = {"use": "work", "type": "both", "country": "US"}
        lines = [v for v in (csv_line1, csv_line2) if v]
        if lines:
            new_addr["line"] = lines
        if csv_city:
            new_addr["city"] = csv_city
        if csv_state:
            new_addr["state"] = csv_state
        if csv_zip:
            new_addr["postalCode"] = csv_zip
        addresses = [new_addr]
    existing_resource["address"] = addresses


def _is_username_collision(exc: Exception) -> bool:
    """Detect Canvas's username-collision business-rule rejection.

    Canvas's exact text:
      "Cannot create Staff with default generated username `mariagarcia`
       because Staff with same first name and last name already exists.
       Please provide unique username in payload."

    We match on phrases unique enough to be unambiguous but resilient to
    minor wording changes ("default generated username" + the suggestion
    to provide one in the payload).
    """
    _, text = _extract_fumage_error_text(exc)
    if not text:
        return False
    lower = text.lower()
    return (
        "default generated username" in lower
        and "username in payload" in lower
    )


def _extract_fumage_error_text(exc: Exception) -> tuple[int | None, str]:
    """Pull (status_code, human message) out of an HTTP error from Fumage.

    Canvas returns FHIR OperationOutcome bodies on 4xx/5xx. We prefer the first
    issue's details.text (that's what was shown in the empirical test for a bad
    role code). Falls back to raw response text, then to str(exc).

    The returned text is also passed through ``humanise_fhir_error`` so pydantic-
    style paths like ``body -> qualification -> 0 -> issuer — field required``
    become readable sentences for the staff admin looking at the results table.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None, humanise_fhir_error(str(exc))

    status_code = getattr(response, "status_code", None)

    try:
        body = response.json()
    except ValueError:
        # response may not be JSON — fall back to raw text path below
        body = None

    if isinstance(body, dict) and body.get("resourceType") == "OperationOutcome":
        for issue in body.get("issue", []) or []:
            details = issue.get("details") or {}
            text = details.get("text") or issue.get("diagnostics")
            if text:
                return status_code, humanise_fhir_error(str(text))

    raw = getattr(response, "text", None)
    if raw:
        return status_code, humanise_fhir_error(str(raw)[:500])

    return status_code, humanise_fhir_error(str(exc))


# Map of path tokens that appear inside pydantic validation error strings to
# friendly labels the end user will recognise. Used as a fallback when the
# more specific path-aware mapping in ``_resolve_field_label`` doesn't hit.
# "qualification" is handled separately because it needs the (N+1) index
# translation.
_FIELD_LABELS = {
    "issuer": "issuer",
    "code": "license type",
    "identifier": "license number",
    "period": "license dates",
    "valueString": "value",
    "valueBoolean": "value",
    "extension": "extension",
    "name": "name",
    "telecom": "contact info",
    "birthDate": "date of birth",
    "qualification": "license",
}


def _resolve_field_label(tokens: list[str]) -> str:
    """Map a FHIR error path to a CSV-column-shaped user-facing label.

    Canvas's pydantic errors arrive as paths like ``qualification -> 0 ->
    code -> text`` or ``identifier -> 0 -> value``. The last token alone
    ("text", "value", "system") is too generic to be useful — the staff
    admin can't tell which CSV column to fix. This resolver inspects the
    parent token to pick the right label, with the simple last-token
    lookup as fallback.

    Mappings reflect what ``build_qualification`` actually writes into
    each FHIR slot:
      - ``code -> text`` ← License Type (no fallback path; blank Type
        produces a blank ``code.text`` and Canvas rejects)
      - ``identifier -> N -> value`` ← License Number
      - ``identifier -> N -> system`` ← Issuing Authority URL (the
        canonical schema URL Canvas's PUT validator demands)
      - ``issuer -> display`` ← License Name (or License Type fallback)
      - ``issuer -> extension -> 0 -> valueString`` ← License Name
        (slot 0 is the issuing-authority-short-name extension)
      - ``issuer -> extension -> 1 -> valueString`` ← License State
        (slot 1 is the issuing-authority-state extension when present)
    """
    if not tokens:
        return ""
    last = tokens[-1]

    # The meaningful parent is the closest non-numeric token before ``last``
    # — pydantic paths interleave field names with array slot indices like
    # ``identifier -> 0 -> system``. Walk backwards skipping integer tokens
    # to find the actual field name.
    parent = ""
    parent_index = -1
    for i in range(len(tokens) - 2, -1, -1):
        if not tokens[i].isdigit():
            parent = tokens[i]
            parent_index = i
            break

    # Slot index immediately preceding ``last`` (when last is in an array
    # element). Used to distinguish extension slot 0 (short-name) from
    # slot 1 (state).
    slot = tokens[-2] if len(tokens) >= 2 and tokens[-2].isdigit() else ""

    # ``identifier`` appears at two FHIR depths:
    #   - inside a qualification → it's the License Number / Issuing
    #     Authority URL slot
    #   - at the Practitioner top level → it's the NPI slot
    # Use presence of "qualification" earlier in the path to disambiguate.
    inside_qualification = "qualification" in tokens

    if parent == "code" and last == "text":
        return "License Type"
    if parent == "identifier" and last == "value":
        return "License Number" if inside_qualification else "NPI"
    if parent == "identifier" and last == "system":
        return "Issuing Authority URL" if inside_qualification else "NPI system"
    if parent == "issuer" and last == "display":
        return "License Name"
    if parent == "telecom" and last == "value":
        # Could be a phone, fax, or email value — we don't have the
        # entry's ``system`` from the path. "Phone, fax, or email" is
        # accurate; readers know which one they care about.
        return "Phone, fax, or email"

    # ``extension -> N -> valueString`` — slot 0 is the short-name
    # extension (License Name), slot 1 (when present) is the state
    # extension (License State). Anything else, fall back to a generic.
    if parent == "extension" and last == "valueString":
        if slot == "0":
            return "License Name"
        if slot == "1":
            return "License State"
        return "Extension value"

    return _FIELD_LABELS.get(last, last)


def humanise_fhir_error(raw: str) -> str:
    """Translate pydantic / FHIR validator error paths into user-friendly text.

    Examples:
      "body -> qualification -> 0 -> issuer — field required (type=value_error)"
        -> "License 1: issuer information is required."

      "body -> qualification -> 2 -> extension -> 1 -> valueString — string does not match regex \\"[ \\\\r\\\\n\\\\t\\\\S]+\\" ..."
        -> "License 3: a required text value is empty."

      "Unable to parse response from downstream server"
        -> "Canvas couldn't process this row — this often happens when a
            duplicate Staff record already exists with the same first/last
            name. Check the Canvas Staff admin or contact Canvas support."

    Falls back to the raw text (unchanged) when no known pattern matches —
    better to show a cryptic message than hide a real one.
    """
    if not raw:
        return raw

    # Canvas's transient gateway error — usually triggered by a duplicate Staff
    # record (sometimes a phantom row left from a partially-failed earlier
    # create). Surface a useful next step instead of the literal proxy text.
    if "Unable to parse response from downstream server" in raw:
        return (
            "Canvas couldn't process this row — this often happens when a "
            "duplicate Staff record already exists with the same first/last "
            "name. Check the Canvas Staff admin or contact Canvas support."
        )

    # Method Not Allowed — only PATCH on Practitioner has historically
    # produced this; we now use PUT for merges, so this is mostly a safety
    # net for future code paths or direct API calls.
    if '"detail":"Method Not Allowed"' in raw or "Method Not Allowed" in raw:
        return (
            "This Canvas API endpoint doesn't accept this kind of update. "
            "Try again with the Skip action, or contact Canvas support if "
            "the problem persists."
        )

    # Strip the (type=...) suffix pydantic appends; adds noise without information.
    cleaned = re.sub(r"\s*\(type=[^)]+\)\s*$", "", raw).strip()

    # Match the leading "body -> ... -> {last_field}" path, then the message.
    match = re.match(r"^body\s*->\s*(.+?)\s+[—\-]\s+(.+)$", cleaned)
    if not match:
        return cleaned

    path_str, message = match.group(1), match.group(2).strip()

    # Find a qualification index if present — translate to "License N+1".
    prefix = ""
    qual_match = re.search(r"qualification\s*->\s*(\d+)", path_str)
    if qual_match:
        prefix = f"License {int(qual_match.group(1)) + 1}: "

    # Resolve the offending field's user-facing label. Path-aware lookup
    # (parent + last token) beats a plain last-token lookup whenever we
    # know the FHIR shape — e.g. ``code -> text`` is the slot the plugin
    # writes License Type into, ``identifier -> 0 -> value`` is License
    # Number, etc. Without these mappings the user sees opaque labels
    # like "text" or "value" and can't tell which CSV column was bad.
    tokens = [t.strip() for t in re.split(r"\s*->\s*", path_str) if t.strip()]
    field_label = _resolve_field_label(tokens)

    # Translate common pydantic message phrases to natural text.
    lower = message.lower()
    if "field required" in lower:
        body = f"{field_label} is required."
    elif "does not match regex" in lower:
        # Canvas's regex "[ \r\n\t\S]+" means "non-empty". We assume that's the
        # common case; we don't try to parse other regexes.
        body = f"{field_label} is required (cannot be blank)."
    elif "none is not an allowed value" in lower:
        body = f"{field_label} is required."
    elif "invalid date" in lower or "not a valid date" in lower:
        body = f"{field_label} is not a valid date."
    else:
        body = f"{field_label}: {message}"

    # Capitalise the first letter of the body for a cleaner sentence.
    if body and body[0].islower():
        body = body[0].upper() + body[1:]

    return f"{prefix}{body}" if prefix else body


class BulkUploadAPI(StaffSessionAuthMixin, SimpleAPI):
    """
    API endpoints for the practitioner bulk upload workflow.

    All endpoints require an authenticated staff session (enforced by
    StaffSessionAuthMixin — the user must be logged into Canvas).
    """

    PREFIX = "/bulk-upload"

    # ------------------------------------------------------------------
    # GET /bulk-upload/template.csv
    # ------------------------------------------------------------------

    @api.get("/template.csv")
    def get_template(self) -> list:
        """Return the CSV template as a downloadable attachment."""
        log.info("[BulkUpload] Template CSV downloaded")
        return [
            Response(
                content=TEMPLATE_CSV.encode("utf-8"),
                status_code=HTTPStatus.OK,
                content_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="practitioner-template.csv"'
                },
            )
        ]

    # ------------------------------------------------------------------
    # POST /bulk-upload/parse-and-validate
    # ------------------------------------------------------------------

    @api.post("/parse-and-validate")
    def parse_and_validate(self) -> list:
        """
        Parse CSV text, validate all records, resolve locations, detect
        existing practitioners via FHIR, and return a structured response.

        Request body: {"csv_text": "..."}
        Response: {errors, warnings, practitioners}
        """
        body = self.request.json()
        csv_text = body.get("csv_text", "")

        if not csv_text:
            return [
                JSONResponse(
                    {"error": "csv_text is required"}, status_code=HTTPStatus.BAD_REQUEST
                )
            ]

        log.info("[BulkUpload] Starting parse-and-validate")

        # 0. Header validation — short-circuits before per-row parsing when
        # the schema is wrong (e.g. a duplicate "State" column shadowing
        # "License State", or a missing "First Name" column). Without this
        # gate, a single header typo would cascade into thousands of
        # confusing per-row errors that all trace back to the same root
        # cause. One clear schema error is much more actionable.
        header_errors = validate_csv_headers(csv_text)
        if header_errors:
            log.info(
                f"[BulkUpload] Header validation failed with "
                f"{len(header_errors)} error(s); aborting before per-row parse"
            )
            return [
                JSONResponse({
                    "errors": header_errors,
                    "warnings": [],
                    "practitioners": [],
                })
            ]

        # 1. Parse and group rows by email
        practitioners, parse_warnings = parse_csv(csv_text)

        all_errors: list[dict[str, Any]] = []
        all_warnings: list[dict[str, Any]] = list(parse_warnings)

        # 2. Validate each merged record.
        # Role codes are not checked here: Canvas validates them at POST time
        # (422 OperationOutcome if unconfigured) and the results table surfaces
        # the per-row reason with a clickable Staff Roles help link.
        validated_practitioners: list[dict[str, Any]] = []
        for prac in practitioners:
            row_num = prac["source_row_number"]
            errors, warnings = validate_practitioner(row_num, prac)
            all_errors.extend(e.to_dict() for e in errors)
            all_warnings.extend(w.to_dict() for w in warnings)
            if not errors:
                validated_practitioners.append(prac)

        # 4. Resolve location names via FHIR (always fetched so location errors
        #    can be collected before the early-return check below)
        try:
            fhir_client = make_fhir_client(self.secrets, self.environment)
        except MissingSecretError as e:
            log.error(f"[BulkUpload] {e}")
            return [
                JSONResponse(
                    {"error": str(e)},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
        location_map = get_location_map(fhir_client)

        # 5. Location hard-error check: unmatched location name blocks import
        for prac in practitioners:
            loc_name = prac.get("primary_practice_location", "").strip()
            if loc_name and loc_name.lower() not in location_map:
                all_errors.append(
                    {
                        "row": prac["source_row_number"],
                        "field": "Primary Practice Location",
                        "value": loc_name,
                        "message": (
                            f"Primary Practice Location '{loc_name}' is not configured "
                            "in this environment. Add it via Canvas admin — "
                            "Settings → Practice Locations."
                        ),
                    }
                )

        # 6. If there are hard errors (from validation or location check), stop here
        if all_errors:
            log.info(
                f"[BulkUpload] Validation found {len(all_errors)} errors; "
                "skipping FHIR lookups"
            )
            return [
                JSONResponse(
                    {
                        "errors": all_errors,
                        "warnings": all_warnings,
                        "practitioners": [],
                    }
                )
            ]

        # 7. Build duplicate-detection indexes from Canvas's Staff ORM. This
        # is the authoritative source — same table Canvas uses for its own
        # uniqueness check during POST /Practitioner — and it sees "phantom"
        # Staff records (Staff rows without a corresponding Practitioner FHIR
        # resource) that a FHIR-only directory misses. If the ORM query
        # itself fails, we degrade gracefully with empty indexes rather than
        # failing the whole upload.
        directory: dict[str, Any] = {
            "by_email": {}, "by_npi": {}, "by_name_dob": {}, "by_name": {}
        }
        try:
            directory = _build_staff_directory()
            log.info(
                f"[BulkUpload] Built staff directory: "
                f"{len(directory['by_email'])} by email, "
                f"{len(directory['by_npi'])} with real NPI, "
                f"{len(directory['by_name_dob'])} with name+DOB, "
                f"{sum(len(v) for v in directory['by_name'].values())} total names indexed"
            )
        except DatabaseError as exc:
            # Narrowed to django.db.DatabaseError per the repo rule that
            # error-handling must surface non-expected exceptions to
            # Sentry. The expected failure here is a database-level error
            # (connection loss, query timeout) — the Staff ORM call is
            # the external dependency. Other exception types (programming
            # bugs, KeyError, etc.) propagate.
            #
            # Without the directory every existing practitioner would be
            # classified "new" and the admin could create duplicates of
            # every Staff record. Surface a top-level warning (row=0 — the
            # UI renders these without a "Row N" prefix) so the admin sees
            # the degraded state before clicking Import. Use log.error
            # because correctness — not just verbosity — is affected.
            log.error(
                f"[BulkUpload] Staff directory query failed; "
                f"duplicate detection disabled for this upload: {exc}"
            )
            all_warnings.append({
                "row": 0,
                "message": (
                    "Duplicate detection unavailable — review existing Staff "
                    "before importing. Every row will be classified as new."
                ),
            })

        by_email = directory["by_email"]
        by_npi = directory["by_npi"]
        by_name_dob = directory["by_name_dob"]
        by_name = directory["by_name"]

        # 8. For each practitioner, run the multi-tier duplicate check.
        # Priority (highest confidence first):
        #   1. Email match  → match_reason="email"
        #   2. Real NPI     → match_reason="npi"
        #   3. Name + DOB   → match_reason="name_dob"
        # If none of the above hit but a name-only match exists, we don't
        # auto-flag (name alone is too weak — multiple John Smiths is
        # common). Instead the count is attached to the per-row result as
        # ``possible_duplicate_count`` and the UI renders a "Possible
        # Duplicate" badge in the Status column so the admin verifies
        # before clicking Import.
        result_practitioners: list[dict[str, Any]] = []
        for prac in validated_practitioners:
            row_num = prac["source_row_number"]
            email = prac["email"]
            email_lower = email.strip().lower()
            npi = (prac.get("npi") or "").strip()
            first_lower = prac["first_name"].strip().lower()
            last_lower = prac["last_name"].strip().lower()
            dob_iso = to_fhir_date(prac.get("dob", "")) if prac.get("dob") else ""
            loc_name = prac.get("primary_practice_location", "").strip()

            # Tier 1: by email
            existing = by_email.get(email_lower)
            match_reason: str | None = "email" if existing else None

            # Tier 2: by real NPI (skip placeholder — sharing it across blank-NPI
            # practitioners would false-positive)
            if not existing and npi and npi != DEFAULT_NPI:
                candidate = by_npi.get(npi)
                if candidate is not None:
                    existing = candidate
                    match_reason = "npi"

            # Tier 3: by name + DOB
            if not existing and first_lower and last_lower and dob_iso:
                candidate = by_name_dob.get((first_lower, last_lower, dob_iso))
                if candidate is not None:
                    existing = candidate
                    match_reason = "name_dob"

            # Possible-duplicate signal: a name-only match (no email/NPI/DOB
            # match) is too weak to auto-flag the row as Existing, but the
            # admin should still see it so they can verify before creating.
            # Surfaced in the per-row result so the UI can render a
            # "Possible Duplicate" badge in the Status column.
            possible_duplicate_count = 0
            if not existing and first_lower and last_lower:
                possible_duplicate_count = len(
                    by_name.get((first_lower, last_lower), [])
                )

            status = "existing" if existing else "new"
            existing_id = f"Practitioner/{existing['id']}" if existing else None

            # For existing rows that point at a real Practitioner FHIR
            # resource, fetch that resource and diff against the CSV's
            # incoming licenses so the preview can show "X total (Y new)".
            # Phantoms (Staff exists but no Practitioner) 404 here — we
            # leave new_license_count=None, the UI shows the total only.
            new_license_count: int | None = None
            renewal_count: int | None = None
            existing_npi: str = ""
            existing_first_name: str = ""
            existing_last_name: str = ""
            existing_email: str = ""
            existing_dob: str = ""
            field_conflicts: list[dict[str, Any]] = []
            existing_read_failed = False
            incoming_licenses = prac.get("licenses", [])
            if existing_id:
                try:
                    existing_resource = read_practitioner(fhir_client, existing_id)
                    existing_values = _extract_existing_field_values(existing_resource)
                    existing_npi = existing_values["npi"]
                    existing_first_name = existing_values["first_name"]
                    existing_last_name = existing_values["last_name"]
                    existing_email = existing_values["email"]
                    existing_dob = existing_values["dob"]
                    field_conflicts = _compute_field_conflicts(prac, existing_values)
                    if incoming_licenses:
                        existing_quals = existing_resource.get("qualification", [])
                        new_licenses, renewals = diff_licenses(
                            existing_quals, incoming_licenses
                        )
                        new_license_count = len(new_licenses)
                        renewal_count = len(renewals)
                except requests.RequestException as exc:
                    # Narrowed to requests.RequestException per the repo
                    # rule: catch only the expected exception from the
                    # external Canvas FHIR call. Phantom records (Staff
                    # row exists with no FHIR Practitioner) 404 here —
                    # that's the documented case and the UI degrades to
                    # "total licenses only". The same catch handles 5xx
                    # and auth blips. Set a per-row flag so the UI can
                    # render "Couldn't preview merge details" instead of
                    # silently showing an incomplete preview.
                    existing_read_failed = True
                    log.warning(
                        f"[BulkUpload] Couldn't read existing record for {email} "
                        f"({existing_id}); merge preview degraded: {exc}"
                    )

            # NPI conflict is a property of the broader field_conflicts list,
            # but we keep it as a top-level boolean so the per-row NPI badge
            # logic stays simple.
            npi_conflict = any(c["field"] == "NPI" for c in field_conflicts)
            # Address conflict: at least one of the address scalar fields
            # differs. Used to enable the 'add as additional address' option
            # in the per-row action dropdown (vs. overwriting the existing
            # address line entry).
            address_conflict = any(
                c["field"] in (
                    "Address Line 1", "Address Line 2", "City", "State", "Zip",
                )
                for c in field_conflicts
            )

            loc_ref = location_map.get(loc_name.lower()) if loc_name else None

            result_practitioners.append(
                {
                    "email": email,
                    "first_name": prac["first_name"],
                    "last_name": prac["last_name"],
                    "role": prac["role"],
                    "phone": prac["phone"],
                    "npi": prac.get("npi", ""),
                    # Send DOB in ISO format (YYYY-MM-DD) so the UI's
                    # NPI-match warning can compare apples-to-apples
                    # against Canvas's birthDate. CSV accepts unpadded
                    # MM-DD-YYYY (e.g. ``3/15/1980`` from Excel/Sheets)
                    # which used to fall through the JS regex and false-
                    # positive as "different DOB" against an ISO Canvas
                    # value. ``to_fhir_date`` handles all accepted CSV
                    # formats (slashes, dashes, ISO, unpadded) and
                    # returns the canonical ISO form.
                    "dob": to_fhir_date(prac["dob"]) if prac.get("dob") else "",
                    "fax": prac.get("fax", ""),
                    "address": {
                        "line1": prac.get("address_line1", ""),
                        "line2": prac.get("address_line2", ""),
                        "city": prac.get("city", ""),
                        "state": prac.get("state", ""),
                        "zip": prac.get("zip", ""),
                    },
                    "location_reference": loc_ref,
                    "primary_practice_location": loc_name,
                    "licenses": incoming_licenses,
                    "status": status,
                    "existing_id": existing_id,
                    "match_reason": match_reason,
                    "new_license_count": new_license_count,
                    "renewal_count": renewal_count,
                    "possible_duplicate_count": possible_duplicate_count,
                    "npi_conflict": npi_conflict,
                    "existing_npi": existing_npi if npi_conflict else "",
                    "existing_first_name": existing_first_name,
                    "existing_last_name": existing_last_name,
                    "existing_email": existing_email,
                    "existing_dob": existing_dob,
                    "field_conflicts": field_conflicts,
                    "address_conflict": address_conflict,
                    "existing_read_failed": existing_read_failed,
                    "source_row_number": row_num,
                }
            )

        log.info(
            f"[BulkUpload] parse-and-validate complete: "
            f"{len(result_practitioners)} practitioners "
            f"({sum(1 for p in result_practitioners if p['status'] == 'new')} new, "
            f"{sum(1 for p in result_practitioners if p['status'] == 'existing')} existing)"
        )

        return [
            JSONResponse(
                {
                    "errors": all_errors,
                    "warnings": all_warnings,
                    "practitioners": result_practitioners,
                }
            )
        ]

    # ------------------------------------------------------------------
    # POST /bulk-upload/create-practitioners
    # ------------------------------------------------------------------

    @api.post("/create-practitioners")
    def create_practitioners(self) -> list:
        """
        Execute the create/merge/skip actions for each practitioner.

        Request body: {"practitioners": [...practitioner records with action field...]}
        Response: {"results": [...per-row results...]}
        """
        body = self.request.json()
        practitioners = body.get("practitioners", [])

        if not practitioners:
            return [
                JSONResponse(
                    {"error": "practitioners list is required"},
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            ]

        log.info(f"[BulkUpload] create-practitioners: processing {len(practitioners)} records")

        try:
            fhir_client = make_fhir_client(self.secrets, self.environment)
        except MissingSecretError as e:
            log.error(f"[BulkUpload] {e}")
            return [
                JSONResponse(
                    {"error": str(e)},
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            ]
        location_map = get_location_map(fhir_client)

        results: list[dict[str, Any]] = []

        for prac in practitioners:
            row_num = prac.get("source_row_number", 0)
            email = prac.get("email", "")
            action = prac.get("action", "skip")

            if action == "create":
                result = self._do_create(fhir_client, prac, location_map, row_num, email)
            elif action == "merge":
                # "Merge to existing record" — fill-missing only, no overwrites.
                result = self._do_merge(fhir_client, prac, row_num, email, strategy="keep")
            elif action == "merge_apply":
                # "Replace record" — overwrite name, DOB, telecom, NPI, address.
                result = self._do_merge(
                    fhir_client, prac, row_num, email,
                    strategy="apply", scope="all", address_mode="overwrite",
                )
            elif action == "merge_replace_address":
                # "Replace address only" — overwrite ONLY the address; keep
                # name, DOB, telecom, and NPI untouched.
                result = self._do_merge(
                    fhir_client, prac, row_num, email,
                    strategy="apply", scope="address_only", address_mode="overwrite",
                )
            elif action == "merge_apply_additional":
                # "Add address as additional" — append the CSV address as a
                # new entry; keep existing primary + all other fields untouched.
                result = self._do_merge(
                    fhir_client, prac, row_num, email,
                    strategy="apply", scope="address_only", address_mode="additional",
                )
            elif action == "skip":
                result = self._do_skip(prac, row_num, email)
            else:
                result = {
                    "row": row_num,
                    "email": email,
                    "status": "error",
                    "staff_key": None,
                    "message": f"Unknown action: {action}",
                }

            results.append(result)

        log.info(f"[BulkUpload] create-practitioners complete: {len(results)} results")

        return [JSONResponse({"results": results})]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _do_create(
        self,
        fhir_client: Any,
        prac: dict[str, Any],
        location_map: dict[str, str],
        row_num: int,
        email: str,
    ) -> dict[str, Any]:
        """Create a new Practitioner via POST /Practitioner.

        First tries with no ``practitioner-user-username`` extension — Canvas
        auto-generates a ``firstlast`` username. If that collides with an
        existing Staff (Canvas returns 422 "Cannot create Staff with default
        generated username..."), retries once with an explicit ``first.last``
        username. Any non-collision error is surfaced after the first attempt.

        Catches any HTTP error so a single bad record doesn't abort the batch.
        """
        log.info(f"[BulkUpload] Creating practitioner: {email}")
        try:
            # parse_and_validate's response packs the five address columns
            # into a nested ``address: {line1, line2, city, state, zip}`` for
            # the UI. The UI echoes that shape back on Import — but
            # ``build_fhir_practitioner`` reads from the flat
            # ``address_line1`` / ``city`` / ``state`` / etc. keys produced
            # by the parser. Without this expansion the FHIR resource has
            # no ``address`` field at all and Canvas silently stores no
            # address for the new staff member.
            _expand_address_for_fhir(prac)
            fhir_resource = build_fhir_practitioner(prac, location_map)
            new_id = create_practitioner(fhir_client, fhir_resource)
        except requests.RequestException as exc:
            # Narrowed to requests.RequestException per the repo rule:
            # catch only the expected exception from the external Canvas
            # FHIR POST. Local logic errors (build_fhir_practitioner
            # raising on malformed data, etc.) propagate to Sentry.
            if not _is_username_collision(exc):
                return self._build_error_result(
                    row_num, prac, email, exc, action="create"
                )
            fallback_username = build_username(
                prac.get("first_name", ""),
                prac.get("last_name", ""),
            )
            if not fallback_username:
                # All-non-ASCII name → can't build first.last → surface
                # the original collision error (admin will need to set
                # the username manually in Canvas).
                return self._build_error_result(
                    row_num, prac, email, exc, action="create"
                )
            log.info(
                f"[BulkUpload] Username collision for {email}; "
                f"retrying with username={fallback_username}"
            )
            try:
                fhir_resource = build_fhir_practitioner(
                    prac, location_map, username_override=fallback_username
                )
                new_id = create_practitioner(fhir_client, fhir_resource)
            except requests.RequestException as retry_exc:
                return self._build_error_result(
                    row_num, prac, email, retry_exc, action="create"
                )

        log.info(f"[BulkUpload] Created practitioner {new_id} for {email}")
        return {
            "row": row_num,
            "email": email,
            "first_name": prac.get("first_name", ""),
            "last_name": prac.get("last_name", ""),
            "status": "created",
            "staff_key": _bare_staff_key(new_id),
            "message": None,
        }

    def _do_merge(
        self,
        fhir_client: Any,
        prac: dict[str, Any],
        row_num: int,
        email: str,
        strategy: str = "keep",
        scope: str = "all",
        address_mode: str = "overwrite",
    ) -> dict[str, Any]:
        """Add new licenses and apply renewals to an existing Practitioner.

        Canvas's Fumage rejects PATCH on Practitioner with 405, so we GET
        the full resource, modify the qualification list locally, and PUT
        the whole resource back.

        ``strategy`` controls non-license field handling:
          ``"keep"`` (default) — fill missing only; populated fields where
          CSV differs are left alone (the conservative merge)
          ``"apply"`` — overwrite populated fields with CSV values (email
          is never changed — FHIR constraint)

        ``address_mode`` is only meaningful when strategy=="apply":
          ``"overwrite"`` — replace existing.address[0] with CSV address
          ``"additional"`` — append CSV address as a new entry; existing
          primary stays

        Two kinds of update happen here:
          * **New license**: incoming entry whose (canonical type, number)
            doesn't appear on the existing record → appended as a new
            ``qualification[]`` entry built from the CSV row.
          * **Renewal**: incoming entry whose (canonical type, number) DOES
            match an existing qualification but whose ``period.start`` /
            ``period.end`` differ → the existing qualification's period is
            replaced in place with the incoming dates. We don't touch the
            qualification's other fields; that keeps issuer state, primary
            flag, etc. exactly as Canvas had them.

        Other resource fields are preserved unchanged.
        """
        existing_id = prac.get("existing_id", "")
        if not existing_id:
            return {
                "row": row_num,
                "email": email,
                "first_name": prac.get("first_name", ""),
                "last_name": prac.get("last_name", ""),
                "status": "error",
                "staff_key": None,
                "message": "No existing_id provided for merge action.",
            }

        log.info(f"[BulkUpload] Merging licenses for {email} ({existing_id})")

        # The UI echoes back the nested ``address: {line1, line2, city,
        # state, zip}`` shape that parse-and-validate emits; the
        # address-touching helpers (_normalize_existing_address,
        # _apply_csv_address) read flat keys (address_line1, city, etc.).
        # Mirror the call in _do_create so merge actually sees the
        # CSV address — without this, every merge silently skipped
        # the address payload and "Replace address only" reported
        # success without changing anything on Canvas.
        _expand_address_for_fhir(prac)

        # Captured before _apply_csv_address mutates the resource — needed
        # so the result message can disclose when address_mode="additional"
        # had no existing primary to coexist with and therefore became the
        # primary instead.
        additional_became_primary = False

        try:
            existing_resource = read_practitioner(fhir_client, existing_id)
            if (
                strategy == "apply"
                and address_mode == "additional"
                and not (existing_resource.get("address") or [])
            ):
                additional_became_primary = True
            existing_qualifications = list(existing_resource.get("qualification", []))
            incoming_licenses = prac.get("licenses", [])

            new_licenses, renewals = diff_licenses(
                existing_qualifications, incoming_licenses
            )

            # If keep-strategy and no license work to do, the merge would
            # be a true no-op. Apply-strategy can still have field
            # overwrites to push (different name/dob/phone/address/NPI),
            # so we don't short-circuit there.
            if strategy == "keep" and not new_licenses and not renewals:
                log.info(f"[BulkUpload] No new licenses or renewals for {email}")
                return {
                    "row": row_num,
                    "email": email,
                    "first_name": prac.get("first_name", ""),
                    "last_name": prac.get("last_name", ""),
                    "status": "skipped",
                    "staff_key": _bare_staff_key(existing_id),
                    "message": "No new licenses or renewals to apply; existing record unchanged.",
                }

            # Apply renewals in place: rebuild the qualification list with
            # any matching existing entry's period replaced by the incoming
            # dates. ``id()`` matching is safe here because diff_licenses
            # returned references into existing_qualifications.
            renewal_targets = {id(target): incoming for incoming, target in renewals}
            updated_qualifications: list[dict[str, Any]] = []
            for qual in existing_qualifications:
                incoming = renewal_targets.get(id(qual))
                if incoming is None:
                    updated_qualifications.append(qual)
                    continue
                new_qual = {**qual, "period": {**(qual.get("period") or {})}}
                if incoming.get("issue_date"):
                    new_qual["period"]["start"] = to_fhir_date(incoming["issue_date"])
                if incoming.get("expiration_date"):
                    new_qual["period"]["end"] = to_fhir_date(incoming["expiration_date"])
                updated_qualifications.append(new_qual)

            # Sanitise existing qualifications' identifiers: rewrite blank
            # / non-canonical system URLs to the schema URL, and drop any
            # identifier whose value is blank (Canvas's PUT validator
            # rejects both shapes; the value-drop preserves the qualification
            # itself with just the meaningless empty identifier slot removed).
            updated_qualifications = [
                _normalize_existing_qualification_identifiers(q)
                for q in updated_qualifications
            ]

            # Fill blank License Name slots (issuer.display + short-name
            # extension valueString) on existing qualifications using the
            # same fallback the create path uses for blank CSV rows:
            # "{License Type} {License State}", e.g. "STATE AK". Drawn
            # from data already on the record (code.text + state
            # extension), never invented.
            updated_qualifications = [
                _normalize_existing_qualification_license_name(q)
                for q in updated_qualifications
            ]

            # Apply-strategy: overwrite existing scalar fields with CSV
            # values BEFORE the fill-missing normalizers run. The fill
            # normalizers no-op when their target field is already
            # populated, so running them after is harmless — they just
            # finish off anything apply didn't touch (e.g. country).
            if strategy == "apply":
                _apply_csv_to_existing(
                    existing_resource, prac,
                    address_mode=address_mode, scope=scope,
                )

            # Sanitise existing telecom entries to satisfy Canvas's "exactly
            # one ContactPoint where system=X and rank=1" PUT constraint.
            # Legacy records sometimes have multiple emails (or zero) at
            # rank=1; we normalise rank metadata only, preserving the
            # underlying contact values so no email/phone/fax data is lost.
            if existing_resource.get("telecom"):
                existing_resource["telecom"] = _normalize_existing_telecom(
                    existing_resource["telecom"]
                )

            # Fill or drop empty Practitioner-level identifier (NPI).
            # Legacy records sometimes have the NPI identifier slot present
            # with blank value, which Canvas's PUT validator now rejects.
            # When the CSV row carries an NPI, write it into the slot —
            # the CSV is the only legitimate source for this value.
            _normalize_existing_practitioner_identifier(
                existing_resource, prac.get("npi", "")
            )

            # Fill missing address fields from CSV (same fill-not-overwrite
            # policy as NPI). Existing records sometimes have no address or
            # a partial address (legacy creates pre-dating this plugin);
            # the merge previously left address untouched so a CSV with
            # full address data silently lost it.
            _normalize_existing_address(existing_resource, prac)

            new_qualifications = [build_qualification(lic) for lic in new_licenses]
            existing_resource["qualification"] = (
                updated_qualifications + new_qualifications
            )
            replace_practitioner(fhir_client, existing_id, existing_resource)
        except requests.RequestException as exc:
            # Narrowed per the repo rule. The expected failures here are
            # from read_practitioner / replace_practitioner (the Canvas
            # FHIR GET and PUT). Local logic errors (KeyError in the
            # ``_normalize_existing_*`` helpers, pydantic validation
            # mismatches, etc.) propagate to Sentry as real bugs.
            return self._build_error_result(row_num, prac, email, exc, action="merge")

        message_parts: list[str] = []
        if new_licenses:
            n = len(new_licenses)
            message_parts.append(f"Added {n} new license{'s' if n != 1 else ''}")
        if renewals:
            r = len(renewals)
            message_parts.append(f"updated {r} renewal{'s' if r != 1 else ''}")
        if strategy == "apply":
            if scope == "address_only":
                if address_mode == "additional":
                    if additional_became_primary:
                        # The admin picked "Add address as additional" but
                        # the existing record carried no address, so the
                        # CSV address became the primary. Disclose this so
                        # the admin understands what they got — they may
                        # want to revisit the row if the intent was to
                        # leave the existing primary alone.
                        message_parts.append(
                            "existing record had no address — added this as primary"
                        )
                    else:
                        message_parts.append("added address as additional entry")
                else:
                    message_parts.append("replaced address")
            else:
                message_parts.append("applied CSV values to existing record")
        message = "; ".join(message_parts) + "." if message_parts else "Merged."

        log.info(
            f"[BulkUpload] {message} for {email} ({existing_id})"
        )
        return {
            "row": row_num,
            "email": email,
            "first_name": prac.get("first_name", ""),
            "last_name": prac.get("last_name", ""),
            "status": "merged",
            "staff_key": _bare_staff_key(existing_id),
            "message": message,
        }

    @staticmethod
    def _build_error_result(
        row_num: int,
        prac: dict[str, Any],
        email: str,
        exc: Exception,
        action: str,
    ) -> dict[str, Any]:
        """Convert an HTTP/FHIR exception into a per-row error result.

        Extracts the FHIR OperationOutcome message when present, and annotates
        role-related errors with the Staff Roles help URL so the UI can turn it
        into a clickable link.
        """
        status_code, detail = _extract_fumage_error_text(exc)
        log.error(
            f"[BulkUpload] {action} failed for {email} "
            f"(row {row_num}, status={status_code}): {detail}"
        )

        message = detail
        detail_lower = detail.lower()
        if "role" in detail_lower and ("staff role" in detail_lower or "role_codes" in detail_lower):
            message = (
                f"{detail} — configure the role in Canvas admin: "
                f"{_STAFF_ROLES_HELP_URL}"
            )

        return {
            "row": row_num,
            "email": email,
            "first_name": prac.get("first_name", ""),
            "last_name": prac.get("last_name", ""),
            "status": "error",
            "staff_key": None,
            "message": message,
        }

    def _do_skip(
        self,
        prac: dict[str, Any],
        row_num: int,
        email: str,
    ) -> dict[str, Any]:
        """Skip — no API call. Returns the existing Staff key when the row
        was matched as Existing; for a New row the user manually skipped,
        staff_key is blank because nothing was created or matched."""
        existing_id = prac.get("existing_id", "")
        log.info(f"[BulkUpload] Skipping {email} ({existing_id or 'new row, no Canvas match'})")
        return {
            "row": row_num,
            "email": email,
            "first_name": prac.get("first_name", ""),
            "last_name": prac.get("last_name", ""),
            "status": "skipped",
            "staff_key": _bare_staff_key(existing_id),
            "message": "Skipped at user request.",
        }
