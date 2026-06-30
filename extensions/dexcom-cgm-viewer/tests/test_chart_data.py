"""Build the JSON payload used by ``GET /data``."""

from __future__ import annotations

import datetime as dt

import pytest

from dexcom_cgm_viewer.services import chart_data, storage
from dexcom_cgm_viewer.models import DexcomEgv


PATIENT = "patient-cd-1"


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)


def _seed_tokens() -> None:
    storage.upsert_tokens(
        PATIENT,
        access_token_ciphertext="A", refresh_token_ciphertext="R",
        expires_at=_now(), dexcom_user_id="X",
        now=_now(), is_initial_connection=True,
    )


def test_disconnected_state_has_no_tokens() -> None:
    payload = chart_data.build_payload(PATIENT, range_days=14, now=_now())
    assert payload.connection_status == "disconnected"
    assert payload.latest_reading is None
    assert payload.summary is None


def test_link_pending_state_when_link_was_sent() -> None:
    storage.upsert_sync_state(PATIENT, link_pending=True, last_link_sent_at=_now())
    payload = chart_data.build_payload(PATIENT, range_days=14, now=_now())
    assert payload.connection_status == "link_pending"


def test_connected_state_with_data() -> None:
    _seed_tokens()
    base = _now() - dt.timedelta(hours=1)
    for offset, value in enumerate([100, 110, 120, 130]):
        DexcomEgv.objects.create(
            patient_id=PATIENT,
            system_time=base + dt.timedelta(minutes=offset * 5),
            display_time=base + dt.timedelta(minutes=offset * 5),
            value_mgdl=value, trend="flat", unit="mg/dL",
        )
    payload = chart_data.build_payload(PATIENT, range_days=7, now=_now())
    assert payload.connection_status == "connected"
    assert payload.latest_reading is not None
    assert payload.latest_reading["value"] == 130
    assert payload.summary is not None
    assert payload.summary["reading_count"] == 4


def test_latest_reading_age_uses_system_time_not_display_time() -> None:
    """Regression: an EDT (UTC-4) patient's display_time is 4 hours behind
    the true system_time. age_seconds must measure against system_time so
    the 'X minutes ago' label reflects real elapsed time, not the lie."""
    _seed_tokens()
    now = _now()
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=now - dt.timedelta(minutes=30),
        display_time=now - dt.timedelta(minutes=30, hours=4),  # EDT-shifted
        value_mgdl=130, trend="flat", unit="mg/dL",
    )
    payload = chart_data.build_payload(PATIENT, range_days=7, now=now)
    assert payload.latest_reading is not None
    # ~30 minutes — not ~4.5 hours.
    assert 1700 <= payload.latest_reading["age_seconds"] <= 1900


def test_window_filter_includes_non_utc_patient_readings() -> None:
    """Regression: filtering by display_time against true-UTC bounds would
    drop or admit up to a half-day for non-UTC patients. system_time-based
    filtering keeps morning-of-now readings for UTC+10 patients in scope."""
    _seed_tokens()
    now = _now()
    # Simulate a Sydney (UTC+10) patient: display_time is 10h ahead of true
    # UTC, so display_time can sit > now (true UTC) even when the reading
    # is fresh by real-world time.
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=now - dt.timedelta(minutes=5),
        display_time=now + dt.timedelta(hours=9, minutes=55),
        value_mgdl=145, trend="flat", unit="mg/dL",
    )
    payload = chart_data.build_payload(PATIENT, range_days=7, now=now)
    # The reading is real-world recent — must appear in the window.
    assert any(p["value"] == 145 for p in payload.egvs)


def test_payload_display_time_has_no_offset() -> None:
    """Regression: ``display_time`` carries no offset in the Dexcom v3
    contract. Sending '+00:00' makes JS double-shift the wall-clock when
    rendering tooltips in the staff browser's timezone."""
    _seed_tokens()
    base = _now() - dt.timedelta(minutes=15)
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base,
        display_time=base - dt.timedelta(hours=4),  # EDT-shifted
        value_mgdl=150, trend="flat", unit="mg/dL",
    )
    payload = chart_data.build_payload(PATIENT, range_days=7, now=_now())
    assert payload.latest_reading is not None
    serialized_latest = payload.latest_reading["display_time"]
    assert "+" not in serialized_latest and not serialized_latest.endswith("Z")
    for point in payload.egvs:
        assert "+" not in point["display_time"]
        assert not point["display_time"].endswith("Z")


def test_naive_iso_strips_offset_and_handles_none() -> None:
    from dexcom_cgm_viewer.services.chart_data import _naive_iso
    assert _naive_iso(None) is None
    tagged = dt.datetime(2026, 5, 6, 8, 30, tzinfo=dt.timezone.utc)
    assert _naive_iso(tagged) == "2026-05-06T08:30:00"


def test_expired_state_when_refresh_failed() -> None:
    _seed_tokens()
    storage.upsert_sync_state(PATIENT, last_error="refresh_failed", last_error_at=_now())
    payload = chart_data.build_payload(PATIENT, range_days=14, now=_now())
    assert payload.connection_status == "expired"


def test_payload_to_dict_serializes_iso_timestamps() -> None:
    storage.upsert_sync_state(PATIENT, last_synced_at=_now(), last_link_sent_at=_now())
    _seed_tokens()
    payload = chart_data.build_payload(PATIENT, range_days=14, now=_now())
    serialized = chart_data.payload_to_dict(payload)
    assert serialized["range"] == "14d"
    assert serialized["last_synced_at"] == _now().isoformat()
    assert serialized["last_link_sent_at"] == _now().isoformat()


def test_unsupported_range_raises() -> None:
    with pytest.raises(ValueError):
        chart_data.build_payload(PATIENT, range_days=42, now=_now())


def test_downsample_returns_input_when_under_limit() -> None:
    points = [{"value": i} for i in range(10)]
    assert chart_data._downsample(points, 600) is points
    assert chart_data._downsample(points, 10) is points


def test_downsample_strides_and_keeps_last_point() -> None:
    points = [{"value": i} for i in range(2000)]
    sampled = chart_data._downsample(points, 600)
    assert len(sampled) <= 601
    assert sampled[0] == {"value": 0}
    # The final reading is always preserved so the chart's right edge is accurate.
    assert sampled[-1] == {"value": 1999}


def test_downsample_zero_limit_is_a_noop() -> None:
    points = [{"value": 1}, {"value": 2}]
    assert chart_data._downsample(points, 0) is points


def test_build_payload_downsamples_long_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_tokens()
    monkeypatch.setattr(chart_data, "MAX_CHART_POINTS", 5)
    base = _now() - dt.timedelta(hours=4)
    rows = [
        DexcomEgv(
            patient_id=PATIENT,
            system_time=base + dt.timedelta(minutes=5 * i),
            display_time=base + dt.timedelta(minutes=5 * i),
            value_mgdl=100 + i, trend="flat", unit="mg/dL",
        )
        for i in range(40)
    ]
    DexcomEgv.objects.bulk_create(rows)
    payload = chart_data.build_payload(PATIENT, range_days=7, now=_now())
    # Chart payload is downsampled to the (patched) cap...
    assert len(payload.egvs) <= 6
    assert payload.egvs[-1]["value"] == 139
    # ...but the summary still reflects all 40 readings.
    assert payload.summary is not None
    assert payload.summary["reading_count"] == 40


def test_payload_excludes_egvs_with_null_value() -> None:
    _seed_tokens()
    base = _now() - dt.timedelta(minutes=10)
    DexcomEgv.objects.create(
        patient_id=PATIENT, system_time=base, display_time=base,
        value_mgdl=None, trend="none", unit="mg/dL",
    )
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base + dt.timedelta(minutes=5),
        display_time=base + dt.timedelta(minutes=5),
        value_mgdl=120, trend="flat", unit="mg/dL",
    )
    payload = chart_data.build_payload(PATIENT, range_days=7, now=_now())
    assert len(payload.egvs) == 1
    assert payload.egvs[0]["value"] == 120
