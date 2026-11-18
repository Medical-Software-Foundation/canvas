"""Facilities for facility rounds and facility blocks: looking them up, and checking one before it is saved."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from canvas_sdk.v1.data.appointment import AppointmentProgressStatus
from canvas_sdk.v1.data.facility import Facility
from canvas_sdk.v1.data.patient import PatientFacilityAddress
from django.db.models import Count

from provider_availability.engine.models import is_uuid
from provider_availability.engine.storage import (
    CACHE_TTL_SECONDS,
    PROVIDER_FACILITIES_INDEX_KEY,
    PROVIDER_FACILITIES_KEY,
    PROVIDER_FACILITIES_PREFIX,
    _get_cache,
)


# A provider's patients, for suggestions: anyone with a visit with them in this
# many days back, or any time ahead.
SUGGESTION_LOOKBACK_DAYS = 365
# Every visit status but cancelled. A positive list, so the condition stays on the
# same visit as the others in the filter.
_KEPT_STATUSES = [s for s in AppointmentProgressStatus.values if s != AppointmentProgressStatus.CANCELLED]


def active_facility_name(facility_id: str) -> str | None:
    """The name of an active facility, or None when the id doesn't match one."""
    # A malformed id raises a validation error inside the query that the sandbox
    # can't catch, so ids are screened before they reach the ORM.
    if not is_uuid(facility_id):
        return None
    name: str | None = Facility.objects.filter(id=facility_id, active=True).values_list("name", flat=True).first()
    return name


def _resolve_facility(
    facility_id: str, switch_on: bool, existing_facility_id: str, existing_facility_name: str
) -> tuple[str | None, str | None]:
    """The facility's name, or the reason it can't be used: ``(name, None)`` or ``(None, reason)``.

    While the switch is off a new one can't be added, but a saved one can still be
    edited without changing its facility. A saved one whose facility was since made
    inactive can be edited too, and keeps the name it was saved with.
    """
    if not switch_on and facility_id != existing_facility_id:
        return None, "off"
    name = active_facility_name(facility_id)
    if name is None and facility_id == existing_facility_id and existing_facility_name:
        name = existing_facility_name
    return (name, None) if name is not None else (None, "inactive")


def check_round(
    body: dict[str, Any], rounds_on: bool, existing_facility_id: str = "", existing_facility_name: str = ""
) -> str | None:
    """Check a rule payload's facility round fields, filling in the facility name.

    Returns an error message, or None when the payload is fine. A payload with no
    facility is clinic availability, so its round fields are cleared. Saved rounds
    follow _resolve_facility.
    """
    facility_id = str(body.get("facility_id") or "").strip()
    if not facility_id:
        body["facility_id"] = ""
        body["facility_name"] = ""
        body["max_visits"] = None
        return None
    name, why = _resolve_facility(facility_id, rounds_on, existing_facility_id, existing_facility_name)
    if why == "off":
        return "Facility rounds are turned off in Settings."
    if name is None:
        return "Choose an active facility for this round."
    body["facility_id"] = facility_id
    body["facility_name"] = name
    # A round books at the provider's primary location (event_sync.round_location_ids),
    # so it keeps no location list of its own.
    body["location_ids"] = []
    return None


# Canvas shows an Admin event titled "<facility name> Visit" as a facility block:
# the facility's name, address and a link to its patient list.
FACILITY_BLOCK_SUFFIX = " Visit"


def facility_block_title(facility_name: str) -> str:
    """The calendar title Canvas reads as a facility block."""
    return f"{facility_name}{FACILITY_BLOCK_SUFFIX}"


def check_block_facility(
    body: dict[str, Any], blocks_on: bool, existing_facility_id: str = "", existing_facility_name: str = ""
) -> str | None:
    """Check a block payload's facility, filling in the name and the title.

    Returns an error message, or None when the payload is fine. A payload with no
    facility is time off, so its facility fields are cleared. Saved facility blocks
    follow _resolve_facility. A facility block blocks every location and is never a hold.
    """
    facility_id = str(body.get("facility_id") or "").strip()
    if not facility_id:
        body["facility_id"] = ""
        body["facility_name"] = ""
        return None
    name, why = _resolve_facility(facility_id, blocks_on, existing_facility_id, existing_facility_name)
    if why == "off":
        return "Facility blocks are turned off in Settings."
    if name is None:
        return "Choose an active facility for this block."
    body["facility_id"] = facility_id
    body["facility_name"] = name
    body["reason"] = facility_block_title(name)
    body["location_ids"] = []
    body["hold_type"] = "none"
    return None


def get_active_facilities() -> list[dict[str, str]]:
    """Every active facility, for the Facility list. Sorted by name."""
    rows = Facility.objects.filter(active=True).values_list("id", "name")
    facilities = [{"id": str(fid), "name": name or ""} for fid, name in rows]
    facilities.sort(key=lambda f: f["name"].lower())
    return facilities


def facility_patient_counts() -> dict[str, int]:
    """How many patients each active facility has on their charts, for a facility block's details.

    One grouped query over active facility addresses.
    """
    rows = (
        PatientFacilityAddress.objects.filter(state="active", facility__active=True)
        .values("facility__id")
        .annotate(patients=Count("patient", distinct=True))
    )
    return {str(r["facility__id"]): int(r["patients"]) for r in rows}


# Each provider's facilities live under their own key, so two saves for different
# providers can't overwrite each other. Reads go by the providers the caller already
# has plus an index of who has saved any; the index is a hint, so an entry lost to two
# saves at once hides nothing for a provider the caller passes.


def _move_legacy_provider_facilities() -> None:
    """Move facilities saved before 0.27.0 (one dict for everyone) to one key per provider."""
    cache = _get_cache()
    legacy = cache.get(PROVIDER_FACILITIES_KEY)
    if not legacy:
        return
    index = list(cache.get(PROVIDER_FACILITIES_INDEX_KEY) or [])
    for pid, ids in legacy.items():
        if ids and str(pid) not in index:
            cache.set(f"{PROVIDER_FACILITIES_PREFIX}{pid}", [str(f) for f in ids], timeout_seconds=CACHE_TTL_SECONDS)
            index.append(str(pid))
    cache.set(PROVIDER_FACILITIES_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)
    cache.delete(PROVIDER_FACILITIES_KEY)


def _stored_facilities(provider_ids: set[str]) -> dict[str, list[str]]:
    """Saved facility ids for these providers plus everyone in the index, in one read."""
    cache = _get_cache()
    pids = sorted({str(p) for p in cache.get(PROVIDER_FACILITIES_INDEX_KEY) or []} | set(provider_ids))
    if not pids:
        return {}
    stored = cache.get_many([f"{PROVIDER_FACILITIES_PREFIX}{pid}" for pid in pids]) or {}
    # get_many can return keys with the cache's own prefix in front, so key by what follows ours.
    return {str(k).split(PROVIDER_FACILITIES_PREFIX, 1)[-1]: [str(f) for f in v or []] for k, v in stored.items()}


def get_provider_facilities(
    active_ids: set[str] | None = None, provider_ids: set[str] | None = None
) -> dict[str, list[str]]:
    """The facility ids saved for each provider in Settings, keyed by provider id.

    Reads the providers passed in plus the index. Facilities made inactive since
    they were saved are left out. Pass the active ids when the caller already has
    them, to save a query.
    """
    _move_legacy_provider_facilities()
    stored = _stored_facilities(provider_ids or set())
    if not stored:
        return {}
    active = active_ids if active_ids is not None else {f["id"] for f in get_active_facilities()}
    result: dict[str, list[str]] = {}
    for pid, ids in stored.items():
        kept = [f for f in ids if f in active]
        if kept:
            result[pid] = kept
    return result


def refresh_provider_facility_ttls(provider_ids: list[str]) -> None:
    """Keep saved facilities from expiring, for these providers and everyone in the index.

    Each key is read right before it is written back, and a key already cleared is
    left cleared. The plugin cache has no compare-and-set, so a Settings save that
    lands between the read and the write for that one provider is written over.
    """
    cache = _get_cache()
    pids = {str(p) for p in cache.get(PROVIDER_FACILITIES_INDEX_KEY) or []} | {str(p) for p in provider_ids}
    for pid in sorted(pids):
        key = f"{PROVIDER_FACILITIES_PREFIX}{pid}"
        value = cache.get(key)
        if value:
            cache.set(key, value, timeout_seconds=CACHE_TTL_SECONDS)


def set_provider_facilities(provider_id: str, facility_ids: Any) -> list[str]:
    """Replace one provider's facilities. Returns the saved ids.

    A facility already saved for the provider and since made inactive is dropped
    rather than refused, so the provider's list can still be changed.
    Raises ValueError when the list isn't a list or adds a facility that isn't active.
    """
    if not isinstance(facility_ids, list):
        raise ValueError("facility_ids must be a list")
    cleaned: list[str] = []
    for value in facility_ids:
        fid = str(value).strip()
        if fid and fid not in cleaned:
            cleaned.append(fid)
    _move_legacy_provider_facilities()
    cache = _get_cache()
    key = f"{PROVIDER_FACILITIES_PREFIX}{provider_id}"
    saved_before = {str(f) for f in cache.get(key) or []}
    active = {f["id"] for f in get_active_facilities()} if cleaned else set()
    if any(fid not in active and fid not in saved_before for fid in cleaned):
        raise ValueError("Choose active facilities only.")
    cleaned = [fid for fid in cleaned if fid in active]
    index = [str(p) for p in cache.get(PROVIDER_FACILITIES_INDEX_KEY) or []]
    if cleaned:
        cache.set(key, cleaned, timeout_seconds=CACHE_TTL_SECONDS)
        if provider_id not in index:
            index.append(provider_id)
            cache.set(PROVIDER_FACILITIES_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)
    else:
        cache.delete(key)
        if provider_id in index:
            index.remove(provider_id)
            cache.set(PROVIDER_FACILITIES_INDEX_KEY, index, timeout_seconds=CACHE_TTL_SECONDS)
    return cleaned


def facility_suggestions(provider_id: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """Active facilities on the charts of a provider's patients, with how many patients each.

    One grouped query. The appointment conditions sit in one filter() so they
    apply to the same visit, and a cancelled visit doesn't count. Most patients
    first, then by name.
    """
    since = (now or datetime.now(UTC)) - timedelta(days=SUGGESTION_LOOKBACK_DAYS)
    rows = (
        PatientFacilityAddress.objects.filter(
            state="active",
            facility__active=True,
            patient__appointments__provider__id=provider_id,
            patient__appointments__entered_in_error__isnull=True,
            patient__appointments__start_time__gte=since,
            patient__appointments__status__in=_KEPT_STATUSES,
        )
        .values("facility__id", "facility__name")
        .annotate(patients=Count("patient", distinct=True))
        .order_by("-patients", "facility__name")
    )
    return [{"id": str(r["facility__id"]), "name": r["facility__name"] or "", "patients": r["patients"]} for r in rows]
