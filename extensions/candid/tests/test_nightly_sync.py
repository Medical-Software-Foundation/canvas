"""Tests for the Candid nightly sync cron and its SyncLog pruning."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from candid.cron.nightly_sync import NightlyCandidSync, _prune_synclog
from candid.models.sync_state import LOG_TYPE_SYNC

from tests.conftest import MOCK_SECRETS

# 07:00 UTC == 02:00 US/Central (CDT) -> the target hour.
AT_TARGET_HOUR = datetime(2026, 6, 3, 7, 0, tzinfo=UTC)
# 12:00 UTC == 07:00 US/Central -> not the target hour.
OFF_TARGET_HOUR = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)


def _build_task(tz: str = "US/Central") -> NightlyCandidSync:
    return NightlyCandidSync(
        event=MagicMock(),
        secrets=dict(MOCK_SECRETS),
        environment={"INSTALLATION_TIME_ZONE": tz},
    )


@patch("candid.cron.nightly_sync._prune_synclog")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_skips_when_not_target_hour(mock_dt, mock_claim, mock_prune):
    mock_dt.now.return_value = OFF_TARGET_HOUR

    assert _build_task().execute() == []
    mock_claim.objects.filter.assert_not_called()
    mock_prune.assert_not_called()


@patch("candid.cron.nightly_sync._prune_synclog")
@patch("candid.cron.nightly_sync.sync_claim_adjudications")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_prunes_even_with_no_claims(mock_dt, mock_claim, mock_sync, mock_prune):
    mock_dt.now.return_value = AT_TARGET_HOUR
    qs = mock_claim.objects.filter.return_value.prefetch_related.return_value
    qs.count.return_value = 0

    assert _build_task().execute() == []
    mock_sync.assert_not_called()
    mock_prune.assert_called_once()


@patch("candid.cron.nightly_sync._prune_synclog")
@patch("candid.cron.nightly_sync.sync_claim_adjudications")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_syncs_claims_then_prunes(mock_dt, mock_claim, mock_sync, mock_prune):
    mock_dt.now.return_value = AT_TARGET_HOUR
    qs = mock_claim.objects.filter.return_value.prefetch_related.return_value
    qs.count.return_value = 2
    qs.iterator.return_value = [MagicMock(), MagicMock()]
    mock_sync.side_effect = [["effect-a"], ["effect-b"]]

    effects = _build_task().execute()

    assert effects == ["effect-a", "effect-b"]
    assert mock_sync.call_count == 2
    mock_prune.assert_called_once()


@patch("candid.cron.nightly_sync._prune_synclog")
@patch("candid.cron.nightly_sync.sync_claim_adjudications")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_isolates_per_claim_failures(mock_dt, mock_claim, mock_sync, mock_prune):
    mock_dt.now.return_value = AT_TARGET_HOUR
    qs = mock_claim.objects.filter.return_value.prefetch_related.return_value
    qs.count.return_value = 2
    qs.iterator.return_value = [MagicMock(), MagicMock()]
    mock_sync.side_effect = [RuntimeError("boom"), ["effect-b"]]

    effects = _build_task().execute()

    assert effects == ["effect-b"]
    mock_prune.assert_called_once()


@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.SyncLog")
def test_prune_collapses_noop_rows_to_latest_per_claim(mock_synclog, mock_claim):
    noop = mock_synclog.objects.filter.return_value
    noop.values.return_value.annotate.return_value.values_list.return_value = [10, 22]
    noop.exclude.return_value.delete.return_value = (5, {"synclog": 5})
    mock_claim.objects.filter.return_value.values_list.return_value = []

    deleted = _prune_synclog()

    mock_synclog.objects.filter.assert_called_once_with(
        log_type=LOG_TYPE_SYNC, payment_effects_count=0, era_ids=""
    )
    noop.exclude.assert_called_once_with(id__in=[10, 22])
    assert deleted == 5


@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.SyncLog")
def test_prune_purges_terminal_claim_rows(mock_synclog, mock_claim):
    noop = MagicMock()
    noop.values.return_value.annotate.return_value.values_list.return_value = []
    noop.exclude.return_value.delete.return_value = (0, {})
    terminal = MagicMock()
    terminal.delete.return_value = (8, {"synclog": 8})
    mock_synclog.objects.filter.side_effect = [noop, terminal]
    mock_claim.objects.filter.return_value.values_list.return_value = ["uuid-1", "uuid-2"]

    deleted = _prune_synclog()

    terminal_call = mock_synclog.objects.filter.call_args_list[1]
    assert terminal_call.kwargs == {"canvas_claim_id__in": ["uuid-1", "uuid-2"]}
    assert deleted == 8


@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.SyncLog")
def test_prune_swallows_db_errors(mock_synclog, mock_claim):
    mock_synclog.objects.filter.side_effect = RuntimeError("db down")

    assert _prune_synclog() == 0
