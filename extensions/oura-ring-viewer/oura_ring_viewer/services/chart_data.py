"""Shape the JSON view-model for ``GET /data`` from rows fetched live.

The rows come from ``services/fetch.py`` and exist only for the length of the
request; nothing here reads or writes Oura data in the database. Connection
status is read from the plugin's own status table.

Series are dense: one slot per calendar day in the window, ``None`` where Oura
had nothing. The chart draws a gap as a gap instead of silently joining the
days on either side of it.
"""

import datetime as dt
from typing import Any, Sequence

from oura_ring_viewer.models import OuraSyncState
from oura_ring_viewer.services.fetch import RECONNECT_ERRORS
from oura_ring_viewer.services.links import link_expired, link_expires_at
from oura_ring_viewer.services.normalize import NormalizedDay
from oura_ring_viewer.services.settings import (
    DISCLAIMER,
    FAMILY_ACTIVITY,
    FAMILY_READINESS,
    FAMILY_SLEEP,
    FAMILY_SPO2,
    RANGE_OPTIONS,
)
from oura_ring_viewer.services.storage import get_sync_state, get_tokens

STATUS_CONNECTED = "connected"
STATUS_EXPIRED = "expired"
STATUS_LINK_PENDING = "link_pending"
STATUS_LINK_EXPIRED = "link_expired"
STATUS_DISCONNECTED = "disconnected"

# (chart key, family, payload key). The chart reads only these keys.
METRICS: tuple[tuple[str, str, str], ...] = (
    ("sleep_score", FAMILY_SLEEP, "score"),
    ("total_sleep_seconds", FAMILY_SLEEP, "total_sleep_seconds"),
    ("resting_hr_bpm", FAMILY_SLEEP, "lowest_heart_rate_bpm"),
    ("hrv_ms", FAMILY_SLEEP, "average_hrv_ms"),
    ("readiness_score", FAMILY_READINESS, "score"),
    ("steps", FAMILY_ACTIVITY, "steps"),
    ("spo2_pct", FAMILY_SPO2, "average_pct"),
)


def connection_status(
    patient_id: str, now: dt.datetime | None = None
) -> tuple[str, OuraSyncState | None]:
    """The patient's connection status and their status row, if any.

    A staff link that ran out unused reads as ``link_expired`` rather than
    leaving the chart waiting forever. Without ``now`` that check is skipped.
    """
    state = get_sync_state(patient_id)
    has_tokens = get_tokens(patient_id) is not None
    last_error = state.last_error if state else ""
    if has_tokens and last_error in RECONNECT_ERRORS:
        return STATUS_EXPIRED, state
    if has_tokens:
        return STATUS_CONNECTED, state
    if state is not None and state.link_pending:
        if now is not None and link_expired(state, now):
            return STATUS_LINK_EXPIRED, state
        return STATUS_LINK_PENDING, state
    return STATUS_DISCONNECTED, state


def window(range_days: int, today: dt.date) -> tuple[dt.date, dt.date]:
    """The inclusive ``range_days`` window ending today."""
    if range_days not in RANGE_OPTIONS:
        raise ValueError(f"unsupported range_days: {range_days}")
    return today - dt.timedelta(days=range_days - 1), today


def build_payload(
    *,
    range_days: int,
    today: dt.date,
    status: str,
    state: OuraSyncState | None,
    rows: Sequence[NormalizedDay] = (),
    forbidden_endpoints: Sequence[str] = (),
    fetch_error: str = "",
    sandbox: bool = False,
) -> dict[str, Any]:
    """Shape everything the chart needs from in-memory rows and status."""
    start_day, _ = window(range_days, today)
    days = [start_day + dt.timedelta(days=i) for i in range(range_days)]
    index = {day: i for i, day in enumerate(days)}

    series: dict[str, list[Any]] = {key: [None] * len(days) for key, _, _ in METRICS}
    for row in rows:
        slot = index.get(row.day)
        if slot is None:
            continue
        for key, family, field in METRICS:
            if family == row.family:
                series[key][slot] = row.payload.get(field)

    return {
        "connection_status": status,
        "last_error": state.last_error if state else "",
        "fetch_error": fetch_error,
        "sandbox": sandbox,
        "forbidden_endpoints": list(forbidden_endpoints),
        "last_synced_at": _iso(state.last_synced_at if state else None),
        "link_sent_at": _iso(state.last_link_sent_at if state else None),
        "link_expires_at": _iso(link_expires_at(state)),
        "range": f"{range_days}d",
        "days": [day.isoformat() for day in days],
        "series": series,
        "latest": {key: _latest(values, days) for key, values in series.items()},
        "averages": {key: _average(values) for key, values in series.items()},
        "has_data": any(value is not None for values in series.values() for value in values),
        "disclaimer": DISCLAIMER,
    }


def _latest(values: list[Any], days: list[dt.date]) -> dict[str, Any] | None:
    """The most recent non-null value in the window, with its day."""
    for value, day in zip(reversed(values), reversed(days)):
        if value is not None:
            return {"value": value, "day": day.isoformat()}
    return None


def _average(values: list[Any]) -> float | None:
    numbers = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 1)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None
