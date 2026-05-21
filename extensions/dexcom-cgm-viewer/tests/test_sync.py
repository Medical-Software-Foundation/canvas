"""On-demand sync engine."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from dexcom_cgm_viewer.lib import storage, sync
from dexcom_cgm_viewer.lib.crypto import TokenCipher
from dexcom_cgm_viewer.lib.dexcom_client import (
    DexcomAuthError,
    TokenSet,
)
from dexcom_cgm_viewer.lib.oauth import RefreshFailed, TokensNotFound
from dexcom_cgm_viewer.models import DexcomEgv, DexcomSummary, DexcomSyncState


PATIENT = "patient-sync-1"


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher()


def _seed(cipher: TokenCipher) -> None:
    storage.upsert_tokens(
        PATIENT,
        access_token_ciphertext=cipher.encrypt("AT"),
        refresh_token_ciphertext=cipher.encrypt("RT"),
        expires_at=_now(),
        dexcom_user_id="DEX",
        now=_now(),
        is_initial_connection=True,
    )


def _records(*display_times: str, value: int = 142) -> list[dict]:
    return [
        {
            "systemTime": ts,
            "displayTime": ts.replace("Z", ""),
            "value": value,
            "unit": "mg/dL",
            "trend": "flat",
        }
        for ts in display_times
    ]


def test_sync_patient_persists_and_recomputes(cipher: TokenCipher) -> None:
    _seed(cipher)
    client = MagicMock()
    client.fetch_egvs.return_value = _records(
        "2026-05-06T08:00:00Z",
        "2026-05-06T08:05:00Z",
    )
    result = sync.sync_patient(
        patient_id=PATIENT, range_days=7, client=client, cipher=cipher, now=_now(),
    )
    assert result.egvs_persisted == 2
    assert result.summaries_written == 1
    assert DexcomEgv.objects.filter(patient_id=PATIENT).count() == 2
    assert DexcomSummary.objects.filter(patient_id=PATIENT).count() == 1
    state = DexcomSyncState.objects.get(patient_id=PATIENT)
    assert state.last_synced_at == _now()
    assert state.last_egv_system_time is not None


def test_sync_patient_purges_old_egvs(cipher: TokenCipher) -> None:
    _seed(cipher)
    cutoff = _now() - dt.timedelta(days=200)
    DexcomEgv.objects.create(
        patient_id=PATIENT, system_time=cutoff, display_time=cutoff,
        value_mgdl=100, trend="flat", unit="mg/dL",
    )
    client = MagicMock()
    client.fetch_egvs.return_value = []
    result = sync.sync_patient(
        patient_id=PATIENT, range_days=7, client=client, cipher=cipher, now=_now(),
    )
    assert result.egvs_purged == 1
    assert DexcomEgv.objects.filter(patient_id=PATIENT).count() == 0


def test_sync_patient_refreshes_on_401(cipher: TokenCipher) -> None:
    _seed(cipher)
    client = MagicMock()
    client.fetch_egvs.side_effect = [
        DexcomAuthError("expired"),
        _records("2026-05-06T08:00:00Z"),
    ]
    client.refresh.return_value = TokenSet(
        access_token="AT2", refresh_token="RT2", expires_in=7200,
        token_type="Bearer", dexcom_user_id="DEX",
    )
    result = sync.sync_patient(
        patient_id=PATIENT, range_days=7, client=client, cipher=cipher, now=_now(),
    )
    assert result.egvs_persisted == 1
    assert client.refresh.call_count == 1


def test_sync_patient_marks_state_when_refresh_permanently_fails(cipher: TokenCipher) -> None:
    _seed(cipher)
    client = MagicMock()
    client.fetch_egvs.side_effect = DexcomAuthError("expired")
    client.refresh.side_effect = DexcomAuthError("revoked")
    with pytest.raises(RefreshFailed):
        sync.sync_patient(
            patient_id=PATIENT, range_days=7, client=client, cipher=cipher, now=_now(),
        )
    state = DexcomSyncState.objects.get(patient_id=PATIENT)
    assert state.last_error == "refresh_failed"


def test_sync_patient_marks_state_when_no_tokens(cipher: TokenCipher) -> None:
    client = MagicMock()
    with pytest.raises(TokensNotFound):
        sync.sync_patient(
            patient_id=PATIENT, range_days=7, client=client, cipher=cipher, now=_now(),
        )
    state = DexcomSyncState.objects.get(patient_id=PATIENT)
    assert state.last_error == "not_connected"


def test_sync_patient_chunks_long_ranges_into_30_day_windows(cipher: TokenCipher) -> None:
    """Dexcom rejects egv requests longer than 30 days; sync must chunk."""
    _seed(cipher)
    client = MagicMock()
    # Three windows for 90 days (30 + 30 + 30): each returns one egv at a
    # different timestamp so we can verify all three were stitched together.
    client.fetch_egvs.side_effect = [
        _records("2026-02-06T12:00:00Z"),
        _records("2026-03-08T12:00:00Z"),
        _records("2026-04-07T12:00:00Z"),
    ]
    result = sync.sync_patient(
        patient_id=PATIENT, range_days=90, client=client, cipher=cipher, now=_now(),
    )
    assert client.fetch_egvs.call_count == 3
    assert result.egvs_persisted == 3
    assert DexcomEgv.objects.filter(patient_id=PATIENT).count() == 3
    # No two windows overlap and they cover end-of-range exactly.
    starts_and_ends = [call.args[1:3] for call in client.fetch_egvs.call_args_list]
    for i in range(1, len(starts_and_ends)):
        assert starts_and_ends[i][0] == starts_and_ends[i - 1][1]
    assert starts_and_ends[-1][1] == _now()


def test_split_window_handles_empty_and_inverted_ranges() -> None:
    base = _now()
    assert sync._split_window(base, base, max_days=30) == []
    assert sync._split_window(base, base - dt.timedelta(days=1), max_days=30) == []


def test_sync_patient_skips_records_with_unparseable_system_time(cipher: TokenCipher) -> None:
    _seed(cipher)
    client = MagicMock()
    client.fetch_egvs.return_value = [
        {"systemTime": "not-a-date", "displayTime": "garbage", "value": 100, "unit": "mg/dL"},
    ]
    result = sync.sync_patient(
        patient_id=PATIENT, range_days=7, client=client, cipher=cipher, now=_now(),
    )
    assert result.egvs_persisted == 0
    assert result.last_egv_system_time is None
