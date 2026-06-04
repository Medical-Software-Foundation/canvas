"""Tests for the one-time SyncLog -> metadata backfill cron."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from candid.cron.backfill_sync_history import (
    CandidSyncHistoryBackfill,
    _backfill_sync_history,
    _merge_history,
    _row_to_entry,
)
from candid.effect_helpers import MAX_SYNC_HISTORY, META_SYNC_HISTORY

from tests.conftest import MOCK_SECRETS

# 05:00 UTC == 00:00 US/Central (CDT) -> the backfill hour (midnight).
AT_BACKFILL_HOUR = datetime(2026, 6, 3, 5, 0, tzinfo=UTC)
# 07:00 UTC == 02:00 US/Central -> the nightly-sync hour, not the backfill hour.
OFF_BACKFILL_HOUR = datetime(2026, 6, 3, 7, 0, tzinfo=UTC)


def _fake_row(claim_id, *, synced_at, log_type="sync", status="", effects=0,
              era_ids="", detail=""):
    row = MagicMock()
    row.canvas_claim_id = claim_id
    row.synced_at = MagicMock()
    row.synced_at.isoformat.return_value = synced_at
    row.log_type = log_type
    row.candid_claim_status = status
    row.payment_effects_count = effects
    row.era_ids = era_ids
    row.detail = detail
    return row


def _build_task(tz: str = "US/Central") -> CandidSyncHistoryBackfill:
    return CandidSyncHistoryBackfill(
        event=MagicMock(),
        secrets=dict(MOCK_SECRETS),
        environment={"INSTALLATION_TIME_ZONE": tz},
    )


# ---------------------------------------------------------------------------
# Cron gate
# ---------------------------------------------------------------------------


@patch("candid.cron.backfill_sync_history._backfill_sync_history", return_value=[])
@patch("candid.cron.backfill_sync_history.datetime")
def test_execute_skips_when_not_backfill_hour(mock_dt, mock_backfill):
    mock_dt.now.return_value = OFF_BACKFILL_HOUR

    assert _build_task().execute() == []
    mock_backfill.assert_not_called()


@patch(
    "candid.cron.backfill_sync_history._backfill_sync_history",
    return_value=["upsert"],
)
@patch("candid.cron.backfill_sync_history.datetime")
def test_execute_runs_backfill_at_midnight(mock_dt, mock_backfill):
    mock_dt.now.return_value = AT_BACKFILL_HOUR

    assert _build_task().execute() == ["upsert"]
    mock_backfill.assert_called_once()


# ---------------------------------------------------------------------------
# Row -> entry mapping
# ---------------------------------------------------------------------------


def test_row_to_entry_maps_legacy_columns_to_metadata_shape():
    row = _fake_row(
        "claim-1",
        synced_at="2026-01-20T00:00:00+00:00",
        log_type="sync",
        status="paid",
        effects=2,
        era_ids="era-1,era-2",
        detail="era-1: $70.00",
    )

    assert _row_to_entry(row) == {
        "synced_at": "2026-01-20T00:00:00+00:00",
        "log_type": "sync",
        "status": "paid",
        "effects": 2,
        "era_ids": ["era-1", "era-2"],
        "detail": "era-1: $70.00",
    }


def test_row_to_entry_empty_era_ids_is_empty_list():
    row = _fake_row("claim-1", synced_at="2026-01-20T00:00:00+00:00", era_ids="")
    assert _row_to_entry(row)["era_ids"] == []


# ---------------------------------------------------------------------------
# Merge semantics
# ---------------------------------------------------------------------------


def test_merge_history_existing_wins_and_sorts_newest_first():
    existing = [{"synced_at": "2026-02-01T00:00:00", "log_type": "sync", "detail": "new"}]
    # same key as existing -> deduped; plus an older legacy-only entry
    legacy = [
        {"synced_at": "2026-02-01T00:00:00", "log_type": "sync", "detail": "new"},
        {"synced_at": "2026-01-01T00:00:00", "log_type": "sync", "detail": "old"},
    ]

    merged = _merge_history(existing, legacy)

    assert [e["detail"] for e in merged] == ["new", "old"]


def test_merge_history_caps_at_max():
    legacy = [
        {"synced_at": f"2026-01-{i:02d}T00:00:00", "log_type": "sync", "detail": str(i)}
        for i in range(1, MAX_SYNC_HISTORY + 6)
    ]

    merged = _merge_history([], legacy)

    assert len(merged) == MAX_SYNC_HISTORY
    # newest-first: highest day numbers retained
    assert merged[0]["detail"] == str(MAX_SYNC_HISTORY + 5)


# ---------------------------------------------------------------------------
# Backfill end to end (mocked SyncLog / Claim / ClaimEffect)
# ---------------------------------------------------------------------------


def _patch_backfill():
    return (
        patch("candid.cron.backfill_sync_history.SyncLog"),
        patch("candid.cron.backfill_sync_history.Claim"),
        patch("candid.cron.backfill_sync_history.ClaimEffect"),
        patch("candid.cron.backfill_sync_history.get_claim_metadata"),
    )


def _make_queryset(rows):
    qs = MagicMock()
    qs.__iter__.return_value = iter(rows)
    qs.delete.return_value = (len(rows), {})
    return qs


def test_backfill_noop_when_no_rows():
    p_log, p_claim, p_ce, p_meta = _patch_backfill()
    with p_log as mock_log, p_claim, p_ce as mock_ce, p_meta:
        mock_log.objects.all.return_value = _make_queryset([])

        assert _backfill_sync_history() == []
        mock_ce.assert_not_called()


def test_backfill_migrates_rows_into_metadata_and_deletes():
    rows = [
        _fake_row("claim-1", synced_at="2026-01-02T00:00:00", detail="b"),
        _fake_row("claim-1", synced_at="2026-01-01T00:00:00", detail="a"),
    ]
    qs = _make_queryset(rows)

    p_log, p_claim, p_ce, p_meta = _patch_backfill()
    with p_log as mock_log, p_claim as mock_claim, p_ce as mock_ce, p_meta as mock_meta:
        mock_log.objects.all.return_value = qs
        claim = MagicMock()
        claim.id = "claim-1"
        mock_claim.objects.filter.return_value = [claim]
        mock_meta.return_value = []  # no existing metadata history
        mock_ce.return_value.upsert_metadata.return_value = "upsert"

        effects = _backfill_sync_history()

        assert effects == ["upsert"]
        # one claim -> one ClaimEffect, keyed by canvas claim id
        mock_ce.assert_called_once_with(claim_id="claim-1")
        call = mock_ce.return_value.upsert_metadata.call_args
        assert call.kwargs["key"] == META_SYNC_HISTORY
        history = json.loads(call.kwargs["value"])
        assert [e["detail"] for e in history] == ["b", "a"]  # newest first
        qs.delete.assert_called_once()


def test_backfill_merges_under_existing_metadata():
    rows = [_fake_row("claim-1", synced_at="2026-01-01T00:00:00", detail="legacy")]
    qs = _make_queryset(rows)

    p_log, p_claim, p_ce, p_meta = _patch_backfill()
    with p_log as mock_log, p_claim as mock_claim, p_ce as mock_ce, p_meta as mock_meta:
        mock_log.objects.all.return_value = qs
        claim = MagicMock()
        claim.id = "claim-1"
        mock_claim.objects.filter.return_value = [claim]
        mock_meta.return_value = [
            {"synced_at": "2026-03-01T00:00:00", "log_type": "sync", "detail": "fresh"}
        ]
        mock_ce.return_value.upsert_metadata.return_value = "upsert"

        _backfill_sync_history()

        history = json.loads(mock_ce.return_value.upsert_metadata.call_args.kwargs["value"])
        # post-migration entry preserved and ordered ahead of the legacy one
        assert [e["detail"] for e in history] == ["fresh", "legacy"]


def test_backfill_drops_orphan_rows_without_an_effect():
    rows = [_fake_row("gone-claim", synced_at="2026-01-01T00:00:00", detail="x")]
    qs = _make_queryset(rows)

    p_log, p_claim, p_ce, p_meta = _patch_backfill()
    with p_log as mock_log, p_claim as mock_claim, p_ce as mock_ce, p_meta:
        mock_log.objects.all.return_value = qs
        mock_claim.objects.filter.return_value = []  # claim no longer exists

        effects = _backfill_sync_history()

        assert effects == []
        mock_ce.assert_not_called()
        qs.delete.assert_called_once()  # orphan rows still cleaned up
