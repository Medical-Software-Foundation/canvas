"""On-demand sync engine: pull egvs, persist, recompute summaries, purge old."""

import datetime as dt
from dataclasses import dataclass
from typing import Any

# Dexcom v3 ``/users/self/egvs`` rejects requests whose ``endDate - startDate``
# is greater than 30 days. The sync engine chunks larger ranges into windows
# bounded by this limit and concatenates the responses.
DEXCOM_EGVS_MAX_WINDOW_DAYS = 30

from dexcom_cgm_viewer.services.crypto import TokenCipher
from dexcom_cgm_viewer.services.storage import (
    purge_old_egvs,
    recompute_summaries_for_dates,
    store_egvs,
    upsert_sync_state,
)
from dexcom_cgm_viewer.services.dexcom_client import (
    DexcomAuthError,
    DexcomClient,
)
from dexcom_cgm_viewer.services.oauth import (
    LoadedTokens,
    RefreshFailed,
    TokensNotFound,
    load_tokens,
    refresh_and_persist,
)
from dexcom_cgm_viewer.services.time_utils import parse_iso8601


@dataclass
class SyncResult:
    """Outcome of a single sync invocation."""

    egvs_persisted: int
    egvs_purged: int
    summaries_written: int
    last_egv_system_time: dt.datetime | None


def sync_patient(
    *,
    patient_id: str,
    range_days: int,
    client: DexcomClient,
    cipher: TokenCipher,
    now: dt.datetime,
) -> SyncResult:
    """Execute a manual 'Sync now' for the given patient and time window.

    Pulls egvs from ``now - range_days`` to ``now``, persists them with
    upsert semantics, purges egvs past the retention horizon, recomputes the
    affected daily summaries, and updates the sync-state watermark.
    """
    try:
        tokens = load_tokens(patient_id, cipher)
    except TokensNotFound:
        upsert_sync_state(
            patient_id,
            last_error="not_connected",
            last_error_at=now,
        )
        raise

    end = now
    start = now - dt.timedelta(days=range_days)
    records: list[dict] = []
    current_tokens = tokens
    for window_start, window_end in _split_window(
        start, end, DEXCOM_EGVS_MAX_WINDOW_DAYS,
    ):
        chunk_records, current_tokens = _fetch_with_refresh(
            patient_id=patient_id,
            client=client,
            cipher=cipher,
            tokens=current_tokens,
            start=window_start,
            end=window_end,
            now=now,
        )
        records.extend(chunk_records)

    persisted = store_egvs(patient_id, records)
    purged = purge_old_egvs(patient_id, now=now)

    affected_dates = sorted({
        parsed.date()
        for record in records
        if (parsed := parse_iso8601(_safe(record.get("displayTime")))) is not None
    })
    summaries_written = recompute_summaries_for_dates(patient_id, affected_dates)

    last_egv_st: dt.datetime | None = None
    for record in records:
        system_time = parse_iso8601(_safe(record.get("systemTime")))
        if system_time is None:
            continue
        if last_egv_st is None or system_time > last_egv_st:
            last_egv_st = system_time

    update_fields: dict = {
        "last_synced_at": now,
        "last_error": "",
        "last_error_at": None,
    }
    if last_egv_st is not None:
        update_fields["last_egv_system_time"] = last_egv_st
    upsert_sync_state(patient_id, **update_fields)

    return SyncResult(
        egvs_persisted=persisted,
        egvs_purged=purged,
        summaries_written=summaries_written,
        last_egv_system_time=last_egv_st,
    )


def _split_window(
    start: dt.datetime,
    end: dt.datetime,
    max_days: int,
) -> list[tuple[dt.datetime, dt.datetime]]:
    """Slice ``[start, end]`` into consecutive windows of at most ``max_days``.

    Returned windows are non-overlapping, in chronological order, and cover
    the full input range exactly. If the input range is empty or inverted,
    an empty list is returned.
    """
    if end <= start:
        return []
    windows: list[tuple[dt.datetime, dt.datetime]] = []
    cursor = start
    step = dt.timedelta(days=max_days)
    while cursor < end:
        next_end = cursor + step
        if next_end > end:
            next_end = end
        windows.append((cursor, next_end))
        cursor = next_end
    return windows


def _fetch_with_refresh(
    *,
    patient_id: str,
    client: DexcomClient,
    cipher: TokenCipher,
    tokens: LoadedTokens,
    start: dt.datetime,
    end: dt.datetime,
    now: dt.datetime,
) -> tuple[list[dict], LoadedTokens]:
    """Run ``fetch_egvs`` and refresh once on 401.

    Returns the records and the (possibly rotated) tokens so the caller can
    reuse a freshly-rotated access token across subsequent chunks of the
    same multi-window sync.
    """
    try:
        return client.fetch_egvs(tokens.access_token, start, end), tokens
    except DexcomAuthError:
        try:
            rotated = refresh_and_persist(
                patient_id, client, cipher, tokens.refresh_token, now=now,
            )
        except RefreshFailed as exc:
            upsert_sync_state(
                patient_id,
                last_error="refresh_failed",
                last_error_at=now,
            )
            raise exc
        return client.fetch_egvs(rotated.access_token, start, end), rotated


def _safe(value: Any) -> str:
    return "" if value is None else str(value)
