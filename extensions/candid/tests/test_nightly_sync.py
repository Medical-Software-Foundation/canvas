"""Tests for the Candid nightly sync cron."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from candid.cron.nightly_sync import NightlyCandidSync

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


@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_skips_when_not_target_hour(mock_dt, mock_claim):
    mock_dt.now.return_value = OFF_TARGET_HOUR

    assert _build_task().execute() == []
    mock_claim.objects.filter.assert_not_called()


@patch("candid.cron.nightly_sync.sync_claim_adjudications")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_no_claims_returns_empty(mock_dt, mock_claim, mock_sync):
    mock_dt.now.return_value = AT_TARGET_HOUR
    qs = mock_claim.objects.filter.return_value
    qs.count.return_value = 0

    assert _build_task().execute() == []
    mock_sync.assert_not_called()


@patch("candid.cron.nightly_sync.sync_claim_adjudications")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_syncs_claims(mock_dt, mock_claim, mock_sync):
    mock_dt.now.return_value = AT_TARGET_HOUR
    qs = mock_claim.objects.filter.return_value
    qs.count.return_value = 2
    qs.iterator.return_value = [MagicMock(), MagicMock()]
    mock_sync.side_effect = [["effect-a"], ["effect-b"]]

    effects = _build_task().execute()

    assert effects == ["effect-a", "effect-b"]
    assert mock_sync.call_count == 2


@patch("candid.cron.nightly_sync.sync_claim_adjudications")
@patch("candid.cron.nightly_sync.Claim")
@patch("candid.cron.nightly_sync.datetime")
def test_execute_isolates_per_claim_failures(mock_dt, mock_claim, mock_sync):
    mock_dt.now.return_value = AT_TARGET_HOUR
    qs = mock_claim.objects.filter.return_value
    qs.count.return_value = 2
    qs.iterator.return_value = [MagicMock(), MagicMock()]
    mock_sync.side_effect = [RuntimeError("boom"), ["effect-b"]]

    effects = _build_task().execute()

    assert effects == ["effect-b"]
