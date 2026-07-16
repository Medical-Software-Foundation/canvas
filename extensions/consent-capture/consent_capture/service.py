"""Shared helpers for reading consent definitions and their on-file status.

Used by both the chart button (to build the picker) and the capture endpoint (to
resolve a definition authoritatively by code). Kept free of handler/UI concerns
so it is straightforward to unit-test.
"""

import re
from datetime import datetime, timezone

from canvas_sdk.v1.data import Patient, PatientConsent, Staff

from logger import log

from consent_capture.constants import (
    ACCEPTED_STATES,
    METHOD_OPTIONS,
    normalize_method_options,
    parse_statement,
)
from consent_capture.models import ConsentCaptureDetail, ConsentDefinition


def active_definitions():
    """Return active consent definitions ordered for display."""
    return list(
        ConsentDefinition.objects.filter(active=True).order_by("sort_order", "display")
    )


def inactive_definitions():
    """Return inactive consent definitions ordered for display. These can't be
    recorded; any consent already on file for one still appears under "On File"
    because that history is built from records, not definitions (see
    ``consent_records``)."""
    return list(
        ConsentDefinition.objects.filter(active=False).order_by("sort_order", "display")
    )


def definition_by_code(code, system=""):
    """Return the active ConsentDefinition matching ``code`` (and ``system`` when
    given), or ``None``. System is matched when provided so two codings that
    share a code across systems stay distinct.

    ``code`` may be empty: some codings carry their identity entirely in ``system``
    (no code configured in Canvas admin), so resolve on ``system`` alone in that
    case. Returns ``None`` only when neither a code nor a system is supplied."""
    code = code or ""
    system = system or ""
    if not code and not system:
        return None
    filters = {"active": True}
    if code:
        filters["code"] = code
    if system:
        filters["system"] = system
    return ConsentDefinition.objects.filter(**filters).order_by("sort_order").first()


def _iso_date(value):
    """Format a date/datetime as an ISO ``YYYY-MM-DD`` string (or '')."""
    if not value:
        return ""
    date = getattr(value, "date", None)
    return (date() if callable(date) else value).isoformat()


def _expiry_active(expired_date, now):
    """Whether ``expired_date`` is still in the future relative to ``now`` (an aware
    UTC datetime), i.e. the consent has not expired.

    Canvas may store the expiry as a plain ``date`` or as a ``datetime`` (naive or
    aware), so normalize before comparing — a bare ``date > datetime`` comparison
    raises ``TypeError``. ``None`` means it never expires (always active)."""
    if expired_date is None:
        return True
    if isinstance(expired_date, datetime):
        if expired_date.tzinfo is None:
            expired_date = expired_date.replace(tzinfo=timezone.utc)
        return expired_date > now
    return expired_date > now.date()


def accepted_status(patient_id, codes):
    """Map each of ``codes`` that has an accepted consent on file to a dict:
    ``{"status", "effective_date", "expired_date"}``. ``status`` is ``"active"``
    (``expired_date`` unset — never expires — or still in the future) or ``"expired"``
    (``expired_date`` has passed). Codes with no accepted consent are absent from the
    map. One query for all codes (avoids an N+1 across definitions).

    The most recent consent per code (by ``effective_date``) is authoritative — it
    reflects the current state after any renewal, and supplies the dates shown on the
    completed cards. Canvas sets ``expired_date`` from the coding's expiration rule."""
    if not patient_id or not codes:
        return {}
    now = datetime.now(timezone.utc)
    out = {}
    rows = (
        PatientConsent.objects.filter(
            patient__id=patient_id,
            category__code__in=list(codes),
            state__in=ACCEPTED_STATES,
        )
        .values_list("category__code", "effective_date", "expired_date")
        .order_by("-effective_date")
    )
    for code, effective_date, expired_date in rows:
        if code in out:
            continue  # keep the most recent (rows are newest-first)
        active = _expiry_active(expired_date, now)
        out[code] = {
            "status": "active" if active else "expired",
            "effective_date": _iso_date(effective_date),
            "expired_date": _iso_date(expired_date),
        }
    return out


def accepted_codes(patient_id, codes):
    """Return the set of ``codes`` with an active (accepted and not expired) consent
    on file for the patient."""
    return {
        code for code, info in accepted_status(patient_id, codes).items()
        if info["status"] == "active"
    }


def _satisfying_pairs(defn):
    """The set of ``(system, code)`` pairs that count as this consent being on file:
    the definition's own coding plus every entry in its ``satisfied_by`` list (its
    configured equivalents). Codes may be empty, so identity is the full pair. Used
    so a patient who completed an equivalent consent isn't prompted again."""
    pairs = set()
    system = getattr(defn, "system", "") or ""
    code = getattr(defn, "code", "") or ""
    if system or code:
        pairs.add((system, code))
    for entry in (getattr(defn, "satisfied_by", None) or []):
        if not isinstance(entry, dict):
            continue
        s = str(entry.get("system") or "").strip()
        c = str(entry.get("code") or "").strip()
        if s or c:
            pairs.add((s, c))
    return pairs


def accepted_status_pairs(patient_id, pairs):
    """Like ``accepted_status`` but keyed by the full ``(system, code)`` pair rather
    than the bare code, so it works when codings share (or lack) a code — some
    codings carry identity only in ``system``. Matches by pair, most-recent-per-pair
    wins, one query. Returns ``{(system, code): {status, effective_date,
    expired_date}}`` for each requested pair that has an accepted consent on file.

    The pair set is filtered in Python (a patient has few consents) so an empty code
    doesn't collide across codings the way a ``category__code__in`` filter would."""
    if not patient_id or not pairs:
        return {}
    want = set(pairs)
    now = datetime.now(timezone.utc)
    out = {}
    rows = (
        PatientConsent.objects.filter(
            patient__id=patient_id,
            state__in=ACCEPTED_STATES,
        )
        .values_list(
            "category__system", "category__code", "effective_date", "expired_date"
        )
        .order_by("-effective_date")
    )
    for system, code, effective_date, expired_date in rows:
        pair = (system or "", code or "")
        if pair not in want or pair in out:
            continue  # keep the most recent (rows are newest-first)
        active = _expiry_active(expired_date, now)
        out[pair] = {
            "status": "active" if active else "expired",
            "effective_date": _iso_date(effective_date),
            "expired_date": _iso_date(expired_date),
        }
    return out


def _combined_status(freshness_by_pair, pairs):
    """Best on-file status across an equivalence set: an active consent on any pair
    wins; otherwise an expired one; otherwise not on file. Returns an info dict
    shaped like ``accepted_status_pairs`` values ('active'/'expired' with dates), or
    ``{}`` when none of the pairs is on file."""
    fallback = None
    for pair in pairs:
        info = freshness_by_pair.get(pair)
        if not info:
            continue
        if info.get("status") == "active":
            return info
        fallback = fallback or info
    return fallback or {}


def consent_records(patient_id):
    """Every accepted consent *record* on file for the patient — one entry per
    recording, NOT deduped by coding — so the hub's "On File" section can show the
    patient's full consent history, including repeats of the same consent with
    different date ranges. Regardless of coding, so consents recorded outside the
    picker (or on codings the plugin doesn't manage) are surfaced read-only too.

    Each entry carries the record's own ``id`` (the FHIR Consent id, used to open
    that exact document), coding identity, dates, ``status`` ("active" when unexpired,
    else "expired"), and the plugin-captured detail (who obtained it, method, who
    consented, capacity statement) joined from ``ConsentCaptureDetail``. Newest first."""
    if not patient_id:
        return []
    now = datetime.now(timezone.utc)
    details = _capture_details(patient_id)
    rows = (
        PatientConsent.objects.filter(
            patient__id=patient_id,
            state__in=ACCEPTED_STATES,
        )
        .values_list(
            "id",
            "category__code",
            "category__system",
            "category__display",
            "effective_date",
            "expired_date",
        )
        .order_by("-effective_date")
    )
    out = []
    for record_id, code, system, display, effective_date, expired_date in rows:
        # Identity is the (system, code) pair; some codings carry it in system alone
        # (empty code), so only skip records with neither.
        if not code and not system:
            continue
        active = _expiry_active(expired_date, now)
        eff_iso = _iso_date(effective_date)
        detail = details.get((system or "", code or "", eff_iso), {})
        out.append(
            {
                "id": str(record_id),
                "code": code or "",
                "system": system or "",
                "display": display or code or system,
                "status": "active" if active else "expired",
                "on_file": active,
                "effective_date": eff_iso,
                "expiration_date": _iso_date(expired_date),
                "obtained_by": detail.get("obtained_by", ""),
                "method": detail.get("method", ""),
                "consented_by": detail.get("consented_by", ""),
                "capacity_statement": detail.get("capacity_statement", ""),
                "pages": detail.get("pages", 0),
            }
        )
    return out


def _capture_details(patient_id):
    """Map ``(system, code, effective_date)`` -> the plugin-stored capture detail for
    the patient (who obtained it, method, who consented, capacity statement). One
    query; used to enrich the read-only On File history. Empty when none stored (e.g.
    consents recorded outside this plugin)."""
    if not patient_id:
        return {}
    rows = ConsentCaptureDetail.objects.filter(patient_id=patient_id).values_list(
        "system",
        "code",
        "effective_date",
        "obtained_by_name",
        "method",
        "consented_by",
        "capacity_statement",
        "pages",
    )
    out = {}
    for system, code, eff, obtained_by, method, consented_by, capacity, pages in rows:
        out[(system or "", code or "", eff or "")] = {
            "obtained_by": obtained_by or "",
            "method": method or "",
            "consented_by": consented_by or "",
            "capacity_statement": capacity or "",
            "pages": int(pages or 0),
        }
    return out


def _picker_item(d, info, is_active):
    """Build one picker payload dict for a definition + its most-recent on-file
    ``info``. Drives the hub's action rows (Required / Optional) and the red chart
    button; the read-only "On File" history is built separately from
    ``consent_records``."""
    state = info.get("status")
    # "on_file" (active) | "expired" (accepted but lapsed) | "needed" (never recorded)
    status = "on_file" if state == "active" else ("expired" if state == "expired" else "needed")
    return {
        "code": d.code,
        "system": d.system,
        "display": d.display or d.code,
        "paragraphs": parse_statement(d.verbiage),
        "method_enabled": bool(d.method_enabled),
        "obtained_by_enabled": bool(d.obtained_by_enabled),
        "capacity_enabled": bool(d.capacity_enabled),
        "method_options": normalize_method_options(d.method_options) or list(METHOD_OPTIONS),
        "questions": d.questions or [],
        "required": bool(d.required),
        "active": is_active,
        "on_file": status == "on_file",
        "status": status,
        "effective_date": info.get("effective_date", ""),
        "expiration_date": info.get("expired_date", ""),
    }


def picker_items(patient_id):
    """Build the *action* payload the picker renders: one dict per active
    (recordable) definition, with its most-recent on-file status. This drives the
    Required / Optional sections and the red chart button (``needs_any``).

    On-file status is computed across each definition's *equivalence set* (its own
    coding plus any configured ``satisfied_by`` codings), by the full
    ``(system, code)`` pair — so a definition with an empty code is still evaluated,
    and a patient who has an equivalent consent on file is treated as done. All
    definitions' pairs are resolved in one query.

    The read-only "On File" history is built separately (see ``consent_records``),
    so recorded consents — including repeats and consents on codings the plugin
    doesn't manage — are listed there rather than here."""
    active = active_definitions()
    all_pairs = set()
    for d in active:
        all_pairs |= _satisfying_pairs(d)
    freshness = accepted_status_pairs(patient_id, all_pairs)
    return [
        _picker_item(d, _combined_status(freshness, _satisfying_pairs(d)), True)
        for d in active
    ]


def has_incomplete_required(patient_id):
    """Whether the patient has at least one required consent not on file (never
    recorded or expired). Drives the red chart button's visibility and the profile
    banner alert, so both mean the same thing: a required consent is missing."""
    return any(
        item.get("required") and not item.get("on_file")
        for item in picker_items(patient_id)
    )


def is_eligible_patient(patient_id):
    """Whether the patient exists, is active, and is not deceased. The banner and
    the red chart button never surface on inactive or deceased patients.

    ``deceased`` is unset (None) for living patients, so exclude only where it is
    explicitly True rather than filtering ``deceased=False`` (which would drop the
    unset ones)."""
    if not patient_id:
        return False
    return (
        Patient.objects.filter(id=patient_id, active=True)
        .exclude(deceased=True)
        .exists()
    )


def _patients_with_active_consent_pair(system, code, now):
    """Set of patient ids whose most-recent accepted consent for the ``(system,
    code)`` pair is still active (unexpired). One query; most-recent-per-patient
    wins. Matches on the full pair (tolerating an empty code) so equivalents that
    lack a code are still counted and empty codes don't collide across codings."""
    rows = (
        PatientConsent.objects.filter(
            category__system=system, category__code=code, state__in=ACCEPTED_STATES
        )
        .values_list("patient__id", "effective_date", "expired_date")
        .order_by("patient__id", "-effective_date")
        .iterator(chunk_size=1000)  # stream: this can be a large table
    )
    have, seen = set(), set()
    for patient_id, _effective_date, expired_date in rows:
        if patient_id in seen:
            continue  # rows are newest-first per patient; keep the first (latest)
        seen.add(patient_id)
        if _expiry_active(expired_date, now):
            have.add(patient_id)
    return have


def patients_missing_required():
    """Set of active, non-deceased patient ids that are missing at least one
    required consent (never recorded, or expired). Used by the admin banner
    backfill, which then removes the banner from anyone no longer in this set
    (including patients who became inactive or deceased).

    A required consent counts as satisfied when *any* coding in its equivalence set
    (its own coding or a configured ``satisfied_by`` equivalent) is on file — the
    same rule the live banner uses — so this stays consistent with the per-patient
    result.

    Bulk computed for scale: one query for eligible patients plus one per distinct
    ``(system, code)`` pair across the required consents (usually a handful, cached
    and reused across definitions that share an equivalent), rather than evaluating
    each patient. Empty when no required consents are configured."""
    required_defs = [
        d for d in active_definitions() if d.required and _satisfying_pairs(d)
    ]
    if not required_defs:
        return set()
    active_ids = set(
        Patient.objects.filter(active=True)
        .exclude(deceased=True)
        .values_list("id", flat=True)
        .iterator(chunk_size=1000)  # stream: Patient can be a large table
    )
    if not active_ids:
        return set()
    now = datetime.now(timezone.utc)
    # One query per distinct pair, reused across definitions that share an equivalent.
    holders_by_pair = {}

    def holders(pair):
        if pair not in holders_by_pair:
            holders_by_pair[pair] = _patients_with_active_consent_pair(
                pair[0], pair[1], now
            )
        return holders_by_pair[pair]

    # "Satisfied" patients have, for *every* required consent, an active consent on
    # at least one of that consent's equivalence pairs.
    satisfied = None
    for d in required_defs:
        have = set()
        for pair in _satisfying_pairs(d):
            have |= holders(pair)
        satisfied = have if satisfied is None else (satisfied & have)
        if not satisfied:
            break
    return active_ids - (satisfied or set())


def _admin_identifiers(raw):
    """Parse the CONSENT_ADMIN_USERS plugin variable into a lower-cased set. Entries
    are separated by commas, semicolons, or newlines."""
    if not raw:
        return set()
    return {part.strip().lower() for part in re.split(r"[,;\n]+", str(raw)) if part.strip()}


# The instance root/superuser always has access, regardless of CONSENT_ADMIN_USERS.
# Canvas provisions it as a Staff named "Canvas Support"; also accept the literal "root".
ROOT_IDENTIFIERS = {"root", "canvas support"}


def _user_identifiers(staff_id):
    """Lower-cased identifiers for the logged-in staff: their id plus first/last/full
    name (from the Staff record). Used to match against the admin allow-list."""
    identifiers = {str(staff_id).strip().lower()}
    row = (
        Staff.objects.filter(id=staff_id)
        .values_list("first_name", "last_name")
        .first()
    )
    if row:
        first = (row[0] or "").strip().lower()
        last = (row[1] or "").strip().lower()
        for value in (first, last, ("%s %s" % (first, last)).strip()):
            if value:
                identifiers.add(value)
    return identifiers


def is_consent_admin(staff_id, allowed_raw):
    """Whether the logged-in staff may open Consent Settings.

    The instance root user (Staff named "Canvas Support", or the literal "root")
    always has access, no matter what. Otherwise the allow-list (CONSENT_ADMIN_USERS
    variable) holds Staff ids and/or full names ("First Last"), matched
    case-insensitively.

    Fails closed: an empty/unset allow-list grants access to **root only** and denies
    every other staff member (a missing config must never open the admin surface)."""
    if not staff_id:
        return False
    # The literal root id is authorized without a Staff lookup.
    if str(staff_id).strip().lower() in ROOT_IDENTIFIERS:
        return True
    identifiers = _user_identifiers(staff_id)
    if identifiers & ROOT_IDENTIFIERS:  # root matched by name (e.g. "Canvas Support")
        return True
    allowed = _admin_identifiers(allowed_raw)
    if not allowed:
        log.warning(
            "CONSENT_ADMIN_USERS is not configured; denying Consent Settings access "
            "to non-root staff %s" % staff_id
        )
        return False
    return bool(identifiers & allowed)
