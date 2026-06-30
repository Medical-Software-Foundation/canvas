"""Build the JSON response for ``GET /data`` from stored egvs + state."""

import datetime as dt
from dataclasses import dataclass
from typing import Any, Optional

from dexcom_cgm_viewer.services.aggregator import Reading, aggregate_window
from dexcom_cgm_viewer.services.storage import (
    fetch_egvs_window,
    get_sync_state,
    get_tokens,
    latest_egv,
)
from dexcom_cgm_viewer.services.settings import MAX_CHART_POINTS, RANGE_OPTIONS
from dexcom_cgm_viewer.services.time_utils import age_seconds


def _naive_iso(value: Optional[dt.datetime]) -> Optional[str]:
    """ISO-format ``display_time`` without a UTC offset.

    Dexcom v3 ``displayTime`` is a wall-clock value with no offset, but it's
    stored UTC-tagged by Django. Sending the ``+00:00`` to the UI causes JS
    to parse it as true UTC and re-render in the browser's timezone, which
    double-shifts the wall-clock by the patient's offset. Stripping the
    offset makes JS parse the same string as local time, restoring the
    original wall-clock the patient experienced.
    """
    if value is None:
        return None
    return value.replace(tzinfo=None).isoformat()


def _downsample(points: list, max_points: int) -> list:
    """Stride-sample ``points`` down to at most ``max_points``.

    Takes every Nth point and always keeps the last one so the chart's right
    edge stays accurate. Used only for the chart payload — summary
    aggregates are computed from the full reading set, not this list.
    """
    if max_points <= 0 or len(points) <= max_points:
        return points
    stride = len(points) // max_points + 1
    sampled = points[::stride]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled


@dataclass
class ChartPayload:
    """Strongly-typed view-model for the chart-drawer JSON response.

    Field types use ``Any`` because the Canvas plugin sandbox rejects PEP-604
    union annotations (``int | None``) on dataclass fields.
    """

    connection_status: str
    link_sent_at: Any
    last_synced_at: Any
    last_error: str
    range_days: int
    latest_reading: Any
    egvs: list
    summary: Any


def _resolve_status(
    *,
    has_tokens: bool,
    last_error: str,
    link_pending: bool,
) -> str:
    if has_tokens and last_error == "refresh_failed":
        return "expired"
    if has_tokens:
        return "connected"
    if link_pending:
        return "link_pending"
    return "disconnected"


def build_payload(
    patient_id: str,
    range_days: int,
    *,
    now: dt.datetime,
) -> ChartPayload:
    """Read every plugin table the chart needs and shape the payload."""
    if range_days not in RANGE_OPTIONS:
        raise ValueError(f"unsupported range_days: {range_days}")

    tokens_row = get_tokens(patient_id)
    state_row = get_sync_state(patient_id)
    last_error = state_row.last_error if state_row else ""
    link_pending = bool(state_row.link_pending) if state_row else False

    status = _resolve_status(
        has_tokens=tokens_row is not None,
        last_error=last_error,
        link_pending=link_pending,
    )

    latest = latest_egv(patient_id)
    latest_reading: Optional[dict] = None
    if latest is not None:
        # ``age_seconds`` uses ``system_time`` (true UTC); ``display_time`` is
        # the patient's wall-clock with no offset (per Dexcom v3) and is sent
        # to the UI as a naive ISO string so JS parses it as local time.
        latest_reading = {
            "value": latest.value_mgdl,
            "unit": "mg/dL",
            "trend": latest.trend,
            "trend_rate": latest.trend_rate,
            "display_time": _naive_iso(latest.display_time),
            "age_seconds": age_seconds(latest.system_time, now=now),
        }

    end = now
    start = now - dt.timedelta(days=range_days)
    egv_rows = fetch_egvs_window(
        patient_id, start_system_time=start, end_system_time=end,
    )
    egvs_payload = _downsample(
        [
            {
                "display_time": _naive_iso(row.display_time),
                "value": row.value_mgdl,
            }
            for row in egv_rows
            if row.value_mgdl is not None
        ],
        MAX_CHART_POINTS,
    )

    summary_payload: Optional[dict] = None
    readings = [
        Reading(display_time=row.display_time, value_mgdl=row.value_mgdl)
        for row in egv_rows
        if row.value_mgdl is not None
    ]
    aggregate = aggregate_window(readings)
    if aggregate is not None:
        summary_payload = {
            "avg_glucose": aggregate.avg_glucose_mgdl,
            "gmi": aggregate.gmi_percent,
            "tir": {
                "low": aggregate.tir_low_pct,
                "target": aggregate.tir_target_pct,
                "high": aggregate.tir_high_pct,
            },
            "hypo_events": aggregate.hypo_events,
            "hyper_events": aggregate.hyper_events,
            "reading_count": aggregate.reading_count,
        }

    return ChartPayload(
        connection_status=status,
        link_sent_at=state_row.last_link_sent_at if state_row else None,
        last_synced_at=state_row.last_synced_at if state_row else None,
        last_error=last_error,
        range_days=range_days,
        latest_reading=latest_reading,
        egvs=egvs_payload,
        summary=summary_payload,
    )


def payload_to_dict(payload: ChartPayload) -> dict[str, Any]:
    """Serialize a ``ChartPayload`` to the JSON shape consumed by the UI."""
    return {
        "connection_status": payload.connection_status,
        "link_sent_at": payload.link_sent_at.isoformat() if payload.link_sent_at else None,
        "last_link_sent_at": payload.link_sent_at.isoformat() if payload.link_sent_at else None,
        "last_synced_at": (
            payload.last_synced_at.isoformat() if payload.last_synced_at else None
        ),
        "last_error": payload.last_error,
        "range": f"{payload.range_days}d",
        "latest_reading": payload.latest_reading,
        "egvs": payload.egvs,
        "summary": payload.summary,
    }
