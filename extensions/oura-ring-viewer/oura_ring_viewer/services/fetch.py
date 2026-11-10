"""Live fetch: read a window of Oura summaries and normalize them in memory.

Nothing fetched here is stored. Under the Oura API Agreement (§3(m)) an
Aggregator "shall not store or cache any User Data or Oura Data", and this
plugin makes Oura data available inside each practice's health record, so it
fetches on demand and only ever holds the result for the length of a request.
The only things persisted are the connection (tokens) and connection status.

One fetch makes one call per endpoint. Tokens are refreshed at most once per
fetch: after a rotation, every later endpoint reuses the new access token.

A 403 on an endpoint skips that family rather than failing the fetch. See
``OuraForbiddenError`` for why a patient can legitimately be missing a family.
If every endpoint is forbidden, nothing is shown and that is recorded.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.normalize import (
    NormalizedDay,
    normalize_activity,
    normalize_readiness,
    normalize_sleep,
    normalize_spo2,
)
from oura_ring_viewer.services.oauth import (
    LoadedTokens,
    RefreshFailed,
    TokensNotFound,
    load_tokens,
    refresh_and_persist,
)
from oura_ring_viewer.services.oura_client import (
    OuraAPIError,
    OuraAuthError,
    OuraClient,
    OuraForbiddenError,
)
from oura_ring_viewer.services.settings import (
    ENDPOINT_DAILY_ACTIVITY,
    ENDPOINT_DAILY_READINESS,
    ENDPOINT_DAILY_SLEEP,
    ENDPOINT_DAILY_SPO2,
    ENDPOINT_SLEEP_PERIODS,
)
from oura_ring_viewer.services.storage import upsert_sync_state

# Short machine-readable codes written to ``OuraSyncState.last_error``. The
# chart maps these to staff-facing wording; they never carry response bodies.
ERROR_NOT_CONNECTED = "not_connected"
ERROR_REFRESH_FAILED = "refresh_failed"
ERROR_AUTH_FAILED = "auth_failed"
ERROR_ALL_FORBIDDEN = "all_forbidden"
ERROR_API = "api_error"

# Errors that mean the stored tokens are dead and the patient must reconnect.
RECONNECT_ERRORS = frozenset({ERROR_REFRESH_FAILED, ERROR_AUTH_FAILED})

_ENDPOINTS: tuple[str, ...] = (
    ENDPOINT_DAILY_SLEEP,
    ENDPOINT_SLEEP_PERIODS,
    ENDPOINT_DAILY_READINESS,
    ENDPOINT_DAILY_ACTIVITY,
    ENDPOINT_DAILY_SPO2,
)


@dataclass
class FetchResult:
    """Normalized rows for the requested window, held in memory only."""

    rows: list[NormalizedDay]
    forbidden_endpoints: tuple[str, ...] = field(default_factory=tuple)


def fetch_window(
    *,
    patient_id: str,
    start_day: dt.date,
    end_day: dt.date,
    client: OuraClient,
    cipher: TokenCipher,
    now: dt.datetime,
) -> FetchResult:
    """Fetch and normalize ``start_day..end_day`` for one patient.

    On success, records the fetch time and clears any error. On failure, the
    connection-status row records a short error code and the original
    exception is re-raised for the API handler to turn into a response.
    """
    try:
        tokens = load_tokens(patient_id, cipher)
    except TokensNotFound:
        _record_error(patient_id, ERROR_NOT_CONNECTED, now)
        raise

    fetched: dict[str, list[dict[str, Any]]] = {}
    forbidden: list[str] = []
    try:
        for endpoint in _ENDPOINTS:
            try:
                records, tokens = _fetch_with_refresh(
                    patient_id=patient_id,
                    client=client,
                    cipher=cipher,
                    tokens=tokens,
                    endpoint=endpoint,
                    start_day=start_day,
                    end_day=end_day,
                    now=now,
                )
            except OuraForbiddenError:
                forbidden.append(endpoint)
                continue
            fetched[endpoint] = records
    except RefreshFailed:
        _record_error(patient_id, ERROR_REFRESH_FAILED, now)
        raise
    except OuraAuthError:
        # Still rejected after a successful refresh.
        _record_error(patient_id, ERROR_AUTH_FAILED, now)
        raise
    except OuraAPIError:
        _record_error(patient_id, ERROR_API, now)
        raise

    if not fetched:
        _record_error(patient_id, ERROR_ALL_FORBIDDEN, now)
        return FetchResult(rows=[], forbidden_endpoints=tuple(forbidden))

    rows = [row for row in _normalize_all(fetched) if start_day <= row.day <= end_day]
    upsert_sync_state(patient_id, last_synced_at=now, last_error="", last_error_at=None)
    return FetchResult(rows=rows, forbidden_endpoints=tuple(forbidden))


def _normalize_all(fetched: dict[str, list[dict[str, Any]]]) -> list[NormalizedDay]:
    """Normalize whatever was fetched; a missing endpoint contributes nothing."""
    rows: list[NormalizedDay] = []
    if ENDPOINT_DAILY_SLEEP in fetched or ENDPOINT_SLEEP_PERIODS in fetched:
        rows += normalize_sleep(
            fetched.get(ENDPOINT_DAILY_SLEEP, []), fetched.get(ENDPOINT_SLEEP_PERIODS, [])
        )
    rows += normalize_readiness(fetched.get(ENDPOINT_DAILY_READINESS, []))
    rows += normalize_activity(fetched.get(ENDPOINT_DAILY_ACTIVITY, []))
    rows += normalize_spo2(fetched.get(ENDPOINT_DAILY_SPO2, []))
    return rows


def _fetch_with_refresh(
    *,
    patient_id: str,
    client: OuraClient,
    cipher: TokenCipher,
    tokens: LoadedTokens,
    endpoint: str,
    start_day: dt.date,
    end_day: dt.date,
    now: dt.datetime,
) -> tuple[list[dict[str, Any]], LoadedTokens]:
    """Fetch one endpoint, refreshing once on 401.

    Returns the records and the possibly-rotated tokens so later endpoints in
    the same fetch reuse the new access token instead of refreshing again.
    """
    try:
        return client.fetch_collection(tokens.access_token, endpoint, start_day, end_day), tokens
    except OuraAuthError:
        rotated = refresh_and_persist(patient_id, client, cipher, tokens.refresh_token, now=now)
        records = client.fetch_collection(rotated.access_token, endpoint, start_day, end_day)
        return records, rotated


def _record_error(patient_id: str, code: str, now: dt.datetime) -> None:
    upsert_sync_state(patient_id, last_error=code, last_error_at=now)
