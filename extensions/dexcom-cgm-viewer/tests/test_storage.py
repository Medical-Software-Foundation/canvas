"""Persistence helpers around the four custom data models."""

from __future__ import annotations

import datetime as dt

import pytest

from dexcom_cgm_viewer.lib import storage
from dexcom_cgm_viewer.models import (
    DexcomEgv,
    DexcomOAuthToken,
    DexcomSummary,
    DexcomSyncState,
)


PATIENT = "patient-storage-1"


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)


def test_upsert_tokens_creates_then_updates() -> None:
    storage.upsert_tokens(
        PATIENT,
        access_token_ciphertext="A1",
        refresh_token_ciphertext="R1",
        expires_at=_now(),
        dexcom_user_id="DEX",
        now=_now(),
        is_initial_connection=True,
    )
    row = DexcomOAuthToken.objects.get(patient_id=PATIENT)
    assert row.access_token == "A1"
    assert row.refresh_token == "R1"
    assert row.connected_at == _now()

    storage.upsert_tokens(
        PATIENT,
        access_token_ciphertext="A2",
        refresh_token_ciphertext="R2",
        expires_at=_now(),
        dexcom_user_id="DEX",
        now=_now() + dt.timedelta(hours=1),
        is_initial_connection=False,
    )
    refreshed = DexcomOAuthToken.objects.get(patient_id=PATIENT)
    assert refreshed.access_token == "A2"
    assert refreshed.refresh_token == "R2"
    assert refreshed.connected_at == _now()  # initial connect timestamp preserved


def test_get_tokens_returns_none_for_unknown_patient() -> None:
    assert storage.get_tokens("missing") is None


def test_upsert_sync_state_round_trip() -> None:
    storage.upsert_sync_state(PATIENT, last_synced_at=_now())
    state = storage.get_sync_state(PATIENT)
    assert state is not None
    assert state.last_synced_at == _now()


def test_store_egvs_skips_records_without_system_time() -> None:
    persisted = storage.store_egvs(PATIENT, [
        {"systemTime": "", "value": 100, "unit": "mg/dL"},
        {"systemTime": "2026-05-06T12:00:00Z", "displayTime": "2026-05-06T08:00:00",
         "value": 142, "unit": "mg/dL", "trend": "flat", "trendRate": 0.5, "status": None},
    ])
    assert persisted == 1
    rows = list(DexcomEgv.objects.filter(patient_id=PATIENT))
    assert len(rows) == 1
    assert rows[0].value_mgdl == 142
    assert rows[0].trend == "flat"
    assert rows[0].unit == "mg/dL"


def test_store_egvs_idempotent_upsert_on_repeat() -> None:
    record = {
        "systemTime": "2026-05-06T12:00:00Z",
        "displayTime": "2026-05-06T08:00:00",
        "value": 142, "unit": "mg/dL",
    }
    assert storage.store_egvs(PATIENT, [record]) == 1
    assert storage.store_egvs(PATIENT, [record]) == 1
    assert DexcomEgv.objects.filter(patient_id=PATIENT).count() == 1


def test_store_egvs_converts_mmol_to_mgdl() -> None:
    storage.store_egvs(PATIENT, [{
        "systemTime": "2026-05-06T12:00:00Z",
        "displayTime": "2026-05-06T08:00:00",
        "value": 7,
        "unit": "mmol/L",
        "trendRate": "0.3",
    }])
    row = DexcomEgv.objects.get(patient_id=PATIENT)
    assert row.value_mgdl == 126
    assert row.unit == "mg/dL"
    assert row.trend_rate == 0.3


def test_store_egvs_handles_invalid_trend_rate() -> None:
    storage.store_egvs(PATIENT, [{
        "systemTime": "2026-05-06T12:00:00Z",
        "displayTime": "2026-05-06T08:00:00",
        "value": 100,
        "unit": "mg/dL",
        "trendRate": "garbage",
    }])
    row = DexcomEgv.objects.get(patient_id=PATIENT)
    assert row.trend_rate is None


def test_store_egvs_falls_back_to_system_time_when_display_time_missing() -> None:
    storage.store_egvs(PATIENT, [{
        "systemTime": "2026-05-06T12:00:00Z",
        "value": 100,
        "unit": "mg/dL",
    }])
    row = DexcomEgv.objects.get(patient_id=PATIENT)
    assert row.display_time == row.system_time


def test_purge_old_egvs_removes_rows_past_retention() -> None:
    now = _now()
    cutoff = now - dt.timedelta(days=200)
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=cutoff, display_time=cutoff,
        value_mgdl=100, trend="flat", unit="mg/dL",
    )
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=now, display_time=now,
        value_mgdl=120, trend="flat", unit="mg/dL",
    )
    deleted = storage.purge_old_egvs(PATIENT, now=now)
    assert deleted == 1
    assert DexcomEgv.objects.filter(patient_id=PATIENT).count() == 1


def test_fetch_egvs_window_returns_ordered_subset() -> None:
    base = _now()
    for offset in range(0, 60, 10):
        DexcomEgv.objects.create(
            patient_id=PATIENT,
            system_time=base + dt.timedelta(minutes=offset),
            display_time=base + dt.timedelta(minutes=offset),
            value_mgdl=100 + offset,
            trend="flat", unit="mg/dL",
        )
    rows = storage.fetch_egvs_window(
        PATIENT,
        start_system_time=base + dt.timedelta(minutes=15),
        end_system_time=base + dt.timedelta(minutes=45),
    )
    assert [r.value_mgdl for r in rows] == [120, 130, 140]


def test_fetch_egvs_window_filters_on_system_time_not_display_time() -> None:
    """Regression: display_time is the patient's wall-clock with no offset
    (per Dexcom v3 spec). Filtering by display_time against true-UTC bounds
    drops up to a half-day of readings for non-UTC patients. The window
    must filter on system_time (true UTC)."""
    base = _now()
    # Simulate an EDT patient (UTC-4): system_time is true UTC, display_time
    # is wall-clock (4h earlier) tagged as UTC by the storage layer.
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base,
        display_time=base - dt.timedelta(hours=4),
        value_mgdl=142, trend="flat", unit="mg/dL",
    )
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base + dt.timedelta(hours=1),
        display_time=base - dt.timedelta(hours=3),
        value_mgdl=143, trend="flat", unit="mg/dL",
    )
    rows = storage.fetch_egvs_window(
        PATIENT,
        start_system_time=base - dt.timedelta(minutes=5),
        end_system_time=base + dt.timedelta(hours=2),
    )
    # Both readings are inside the true-UTC window. If the filter used
    # display_time, the EDT-shifted timestamps would fall below `start` and
    # both rows would be dropped.
    assert [r.value_mgdl for r in rows] == [142, 143]


def test_latest_egv_orders_by_system_time_not_display_time() -> None:
    """Regression: latest_egv must rank by true-UTC, not the wall-clock lie."""
    base = _now()
    older_system_newer_display = DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base,
        display_time=base + dt.timedelta(hours=5),
        value_mgdl=100, trend="flat", unit="mg/dL",
    )
    newer_system_older_display = DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base + dt.timedelta(minutes=5),
        display_time=base,
        value_mgdl=200, trend="flat", unit="mg/dL",
    )
    latest = storage.latest_egv(PATIENT)
    assert latest is not None
    assert latest.value_mgdl == 200
    _ = older_system_newer_display, newer_system_older_display


def test_latest_egv_returns_most_recent() -> None:
    base = _now()
    DexcomEgv.objects.create(
        patient_id=PATIENT, system_time=base, display_time=base,
        value_mgdl=100, trend="flat", unit="mg/dL",
    )
    DexcomEgv.objects.create(
        patient_id=PATIENT,
        system_time=base + dt.timedelta(minutes=5),
        display_time=base + dt.timedelta(minutes=5),
        value_mgdl=110, trend="flat", unit="mg/dL",
    )
    latest = storage.latest_egv(PATIENT)
    assert latest is not None
    assert latest.value_mgdl == 110


def test_latest_egv_returns_none_when_empty() -> None:
    assert storage.latest_egv("nobody") is None


def test_recompute_summaries_writes_one_row_per_date() -> None:
    base = dt.datetime(2026, 5, 6, 8, 0, tzinfo=dt.timezone.utc)
    for offset, value in enumerate([100, 110, 120, 130]):
        DexcomEgv.objects.create(
            patient_id=PATIENT,
            system_time=base + dt.timedelta(minutes=offset * 5),
            display_time=base + dt.timedelta(minutes=offset * 5),
            value_mgdl=value, trend="flat", unit="mg/dL",
        )
    written = storage.recompute_summaries_for_dates(PATIENT, [dt.date(2026, 5, 6)])
    assert written == 1
    summary = DexcomSummary.objects.get(patient_id=PATIENT, date=dt.date(2026, 5, 6))
    assert summary.reading_count == 4
    assert summary.avg_glucose_mgdl == 115.0


def test_recompute_summaries_deletes_summary_when_no_readings_remain() -> None:
    DexcomSummary.objects.create(
        patient_id=PATIENT, date=dt.date(2026, 5, 6),
        avg_glucose_mgdl=100, gmi_percent=5,
        tir_low_pct=0, tir_target_pct=100, tir_high_pct=0,
        hypo_events=0, hyper_events=0, reading_count=10,
    )
    written = storage.recompute_summaries_for_dates(PATIENT, [dt.date(2026, 5, 6)])
    assert written == 0
    assert not DexcomSummary.objects.filter(patient_id=PATIENT, date=dt.date(2026, 5, 6)).exists()


def test_delete_all_for_patient_purges_every_table() -> None:
    storage.upsert_tokens(
        PATIENT, access_token_ciphertext="x", refresh_token_ciphertext="y",
        expires_at=_now(), dexcom_user_id="d", now=_now(),
        is_initial_connection=True,
    )
    storage.upsert_sync_state(PATIENT, last_synced_at=_now())
    DexcomEgv.objects.create(
        patient_id=PATIENT, system_time=_now(), display_time=_now(),
        value_mgdl=100, trend="flat", unit="mg/dL",
    )
    DexcomSummary.objects.create(
        patient_id=PATIENT, date=dt.date(2026, 5, 6),
        avg_glucose_mgdl=100, gmi_percent=5,
        tir_low_pct=0, tir_target_pct=100, tir_high_pct=0,
        hypo_events=0, hyper_events=0, reading_count=1,
    )
    storage.delete_all_for_patient(PATIENT)
    assert not DexcomOAuthToken.objects.filter(patient_id=PATIENT).exists()
    assert not DexcomSyncState.objects.filter(patient_id=PATIENT).exists()
    assert not DexcomEgv.objects.filter(patient_id=PATIENT).exists()
    assert not DexcomSummary.objects.filter(patient_id=PATIENT).exists()
