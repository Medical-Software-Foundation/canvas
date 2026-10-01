"""Persistence helpers around the four custom data models.

Centralizes upsert + purge logic so handlers don't reach into the ORM
directly. All datetimes are UTC; conversion to patient timezone happens at
read time in ``chart_data``.
"""

import datetime as dt
from typing import Any, Iterable

from dexcom_cgm_viewer.services.aggregator import Reading, aggregate_range
from dexcom_cgm_viewer.services.settings import EGV_RETENTION_DAYS
from dexcom_cgm_viewer.services.time_utils import parse_iso8601, to_mgdl
from dexcom_cgm_viewer.models import (
    DexcomEgv,
    DexcomOAuthToken,
    DexcomSummary,
    DexcomSyncState,
)

# The SDK's bulk_create wrapper rejects batches larger than MAX_BULK_SIZE
# (10,000). A 90-day sync is ~26k readings, so writes are chunked below this.
_BULK_CHUNK_SIZE = 10_000


def upsert_tokens(
    patient_id: str,
    *,
    access_token_ciphertext: str,
    refresh_token_ciphertext: str,
    expires_at: dt.datetime,
    dexcom_user_id: str,
    now: dt.datetime,
    is_initial_connection: bool,
) -> None:
    """Insert or update the encrypted token row for the patient."""
    defaults = {
        "access_token": access_token_ciphertext,
        "refresh_token": refresh_token_ciphertext,
        "expires_at": expires_at,
        "dexcom_user_id": dexcom_user_id,
        "last_refresh_at": now,
    }
    if is_initial_connection:
        defaults["connected_at"] = now
    DexcomOAuthToken.objects.update_or_create(patient_id=patient_id, defaults=defaults)


def get_tokens(patient_id: str) -> DexcomOAuthToken | None:
    """Return the raw stored row for the given patient, or ``None``."""
    return DexcomOAuthToken.objects.filter(patient_id=patient_id).first()


def delete_all_for_patient(patient_id: str) -> None:
    """Disconnect: remove every plugin row for the patient.

    Performs four sequential deletes. Each Django ORM call is wrapped in its
    own implicit transaction; we don't wrap the whole sequence because the
    plugin sandbox does not allow ``django.db.transaction``. Tokens are
    deleted first so a partial failure still leaves the patient effectively
    disconnected (no tokens means no further sync activity).
    """
    DexcomOAuthToken.objects.filter(patient_id=patient_id).delete()
    DexcomSyncState.objects.filter(patient_id=patient_id).delete()
    DexcomEgv.objects.filter(patient_id=patient_id).delete()
    DexcomSummary.objects.filter(patient_id=patient_id).delete()


def upsert_sync_state(patient_id: str, **fields: Any) -> DexcomSyncState:
    """Update or create the sync-state row, only writing supplied fields."""
    state, _ = DexcomSyncState.objects.update_or_create(
        patient_id=patient_id, defaults=fields,
    )
    return state


def get_sync_state(patient_id: str) -> DexcomSyncState | None:
    """Return the sync-state row, or ``None`` if the patient never connected."""
    return DexcomSyncState.objects.filter(patient_id=patient_id).first()


def _chunks(items: list, size: int) -> Iterable[list]:
    """Yield consecutive ``size``-length slices of ``items``."""
    for start in range(0, len(items), size):
        yield items[start:start + size]


def store_egvs(patient_id: str, records: Iterable[dict]) -> int:
    """Upsert egv records for the patient. Returns count of records persisted.

    Records are accepted in Dexcom's response shape (``systemTime``,
    ``displayTime``, ``value``, ``unit``, ``trend``, ``trendRate``,
    ``status``). They are de-duplicated by ``(patient_id, system_time)`` —
    a Postgres ``ON CONFLICT`` upsert cannot touch the same row twice in one
    statement — then written with a chunked bulk upsert so a 90-day sync is
    a handful of round-trips instead of one per reading.
    """
    by_system_time: dict[dt.datetime, DexcomEgv] = {}
    for record in records:
        system_time = parse_iso8601(_safe_str(record.get("systemTime")))
        if system_time is None:
            continue
        display_time = parse_iso8601(_safe_str(record.get("displayTime"))) or system_time
        unit = _safe_str(record.get("unit")) or "mg/dL"
        # Last write wins for a repeated system_time, matching the prior
        # per-record update_or_create behavior.
        by_system_time[system_time] = DexcomEgv(
            patient_id=patient_id,
            system_time=system_time,
            display_time=display_time,
            value_mgdl=to_mgdl(record.get("value"), unit),
            trend=_safe_str(record.get("trend")),
            trend_rate=_safe_float(record.get("trendRate")),
            status=_safe_str(record.get("status")),
            unit="mg/dL",
        )

    rows = list(by_system_time.values())
    update_fields = [
        "display_time", "value_mgdl", "trend", "trend_rate", "status", "unit",
    ]
    for chunk in _chunks(rows, _BULK_CHUNK_SIZE):
        DexcomEgv.objects.bulk_create(
            chunk,
            update_conflicts=True,
            unique_fields=["patient_id", "system_time"],
            update_fields=update_fields,
        )
    return len(rows)


def purge_old_egvs(patient_id: str, *, now: dt.datetime) -> int:
    """Delete egv rows older than the retention horizon. Returns count deleted."""
    cutoff = now - dt.timedelta(days=EGV_RETENTION_DAYS)
    deleted, _ = DexcomEgv.objects.filter(
        patient_id=patient_id, system_time__lt=cutoff,
    ).delete()
    return int(deleted)


def fetch_egvs_window(
    patient_id: str,
    *,
    start_system_time: dt.datetime,
    end_system_time: dt.datetime,
) -> list[DexcomEgv]:
    """Return egvs whose ``system_time`` (true UTC) is in the window, ordered.

    Filters and orders on ``system_time`` rather than ``display_time``:
    ``display_time`` is the patient's wall-clock with no offset (per Dexcom
    v3), so it can't be compared against a true-UTC reference without
    knowing the patient timezone. ``system_time`` is the canonical UTC
    timeline used for all time math in the plugin.
    """
    queryset = DexcomEgv.objects.filter(
        patient_id=patient_id,
        system_time__gte=start_system_time,
        system_time__lte=end_system_time,
    ).order_by("system_time")
    return list(queryset)


def latest_egv(patient_id: str) -> DexcomEgv | None:
    """Most recent reading for the patient by ``system_time`` (true UTC)."""
    return (
        DexcomEgv.objects.filter(patient_id=patient_id)
        .order_by("-system_time")
        .first()
    )


def recompute_summaries_for_dates(
    patient_id: str, dates: Iterable[dt.date],
) -> int:
    """Rebuild ``DexcomSummary`` rows for the supplied dates.

    All egvs spanning the requested dates are fetched in a single query and
    bucketed by local date by ``aggregate_range``, rather than issuing one
    SELECT per date. Returns number of summary rows written or updated; dates
    with no readings have their summary row deleted.
    """
    date_list = sorted(set(dates))
    if not date_list:
        return 0

    first, last = date_list[0], date_list[-1]
    span_start = dt.datetime(first.year, first.month, first.day, tzinfo=dt.timezone.utc)
    span_end = (
        dt.datetime(last.year, last.month, last.day, tzinfo=dt.timezone.utc)
        + dt.timedelta(days=1)
        - dt.timedelta(microseconds=1)
    )
    rows = DexcomEgv.objects.filter(
        patient_id=patient_id,
        display_time__gte=span_start,
        display_time__lte=span_end,
    ).order_by("display_time")
    readings = [
        Reading(display_time=row.display_time, value_mgdl=row.value_mgdl)
        for row in rows
        if row.value_mgdl is not None
    ]
    aggregates = aggregate_range(readings)

    written = 0
    for day in date_list:
        aggregate = aggregates.get(day)
        if aggregate is None:
            DexcomSummary.objects.filter(patient_id=patient_id, date=day).delete()
            continue
        DexcomSummary.objects.update_or_create(
            patient_id=patient_id,
            date=day,
            defaults={
                "avg_glucose_mgdl": aggregate.avg_glucose_mgdl,
                "gmi_percent": aggregate.gmi_percent,
                "tir_low_pct": aggregate.tir_low_pct,
                "tir_target_pct": aggregate.tir_target_pct,
                "tir_high_pct": aggregate.tir_high_pct,
                "hypo_events": aggregate.hypo_events,
                "hyper_events": aggregate.hyper_events,
                "reading_count": aggregate.reading_count,
            },
        )
        written += 1
    return written


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
