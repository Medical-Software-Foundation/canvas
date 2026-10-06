"""Tests for the Candid nightly sync cron."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from candid.cron.nightly_sync import (
    BATCH_TIME_BUDGET,
    CURSOR_CACHE_KEY,
    LOCK_CACHE_KEY,
    NightlyCandidSync,
)

from tests.conftest import MOCK_SECRETS

# 07:00 UTC == 02:00 US/Central (CDT) -> the target hour.
AT_TARGET_HOUR = datetime(2026, 6, 3, 7, 0, tzinfo=UTC)
# 12:00 UTC == 07:00 US/Central -> not the target hour.
OFF_TARGET_HOUR = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)


class FakeCache:
    """Dict-backed stand-in for the plugin cache."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = dict(data or {})

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value, timeout_seconds: int | None = None) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


def _build_task(tz: str = "US/Central") -> NightlyCandidSync:
    return NightlyCandidSync(
        event=MagicMock(),
        secrets=dict(MOCK_SECRETS),
        environment={"INSTALLATION_TIME_ZONE": tz},
    )


def _claim(claim_id: str) -> MagicMock:
    claim = MagicMock()
    claim.id = claim_id
    return claim


@pytest.fixture
def mocks():
    cache = FakeCache()
    with (
        patch("candid.cron.nightly_sync.get_cache", return_value=cache),
        patch("candid.cron.nightly_sync.datetime") as mock_dt,
        patch("candid.cron.nightly_sync.Claim") as mock_claim,
        patch("candid.cron.nightly_sync.sync_claim_adjudications") as mock_sync,
    ):
        mock_dt.now.return_value = AT_TARGET_HOUR
        ordered = mock_claim.objects.filter.return_value.order_by.return_value
        ordered.filter.return_value = ordered
        yield {"cache": cache, "dt": mock_dt, "qs": ordered, "sync": mock_sync}


def test_execute_skips_when_not_target_hour(mocks):
    mocks["dt"].now.return_value = OFF_TARGET_HOUR

    assert _build_task().execute() == []
    mocks["sync"].assert_not_called()


def test_execute_no_claims_returns_empty(mocks):
    mocks["qs"].iterator.return_value = []

    assert _build_task().execute() == []
    mocks["sync"].assert_not_called()
    assert CURSOR_CACHE_KEY not in mocks["cache"].data


def test_execute_syncs_claims_and_completes_cycle(mocks):
    mocks["qs"].iterator.return_value = [_claim("a"), _claim("b")]
    mocks["sync"].side_effect = [["effect-a"], ["effect-b"]]

    effects = _build_task().execute()

    assert effects == ["effect-a", "effect-b"]
    assert mocks["sync"].call_count == 2
    assert CURSOR_CACHE_KEY not in mocks["cache"].data
    assert LOCK_CACHE_KEY not in mocks["cache"].data


def test_execute_isolates_per_claim_failures(mocks):
    mocks["qs"].iterator.return_value = [_claim("a"), _claim("b")]
    mocks["sync"].side_effect = [RuntimeError("boom"), ["effect-b"]]

    effects = _build_task().execute()

    assert effects == ["effect-b"]


def test_execute_stops_at_batch_size_and_saves_cursor(mocks):
    mocks["qs"].iterator.return_value = [_claim("a"), _claim("b"), _claim("c")]
    mocks["sync"].side_effect = lambda claim, secrets: [f"effect-{claim.id}"]

    with patch("candid.cron.nightly_sync.MAX_CLAIMS_PER_BATCH", 2):
        effects = _build_task().execute()

    assert effects == ["effect-a", "effect-b"]
    assert mocks["cache"].data[CURSOR_CACHE_KEY] == "b"
    assert LOCK_CACHE_KEY not in mocks["cache"].data


def test_execute_stops_when_time_budget_is_spent(mocks):
    mocks["qs"].iterator.return_value = [_claim("a"), _claim("b")]
    mocks["sync"].side_effect = lambda claim, secrets: [f"effect-{claim.id}"]
    over_budget = AT_TARGET_HOUR + BATCH_TIME_BUDGET + timedelta(seconds=1)
    mocks["dt"].now.side_effect = [AT_TARGET_HOUR, AT_TARGET_HOUR, over_budget]

    effects = _build_task().execute()

    assert effects == ["effect-a"]
    assert mocks["cache"].data[CURSOR_CACHE_KEY] == "a"


def test_execute_resumes_after_cursor_outside_target_hour(mocks):
    mocks["dt"].now.return_value = OFF_TARGET_HOUR
    mocks["cache"].data[CURSOR_CACHE_KEY] = "b"
    mocks["qs"].iterator.return_value = [_claim("c")]
    mocks["sync"].return_value = ["effect-c"]

    effects = _build_task().execute()

    assert effects == ["effect-c"]
    mocks["qs"].filter.assert_called_once_with(id__gt="b")
    assert CURSOR_CACHE_KEY not in mocks["cache"].data


def test_execute_skips_while_previous_batch_holds_lock(mocks):
    mocks["cache"].data[LOCK_CACHE_KEY] = AT_TARGET_HOUR.isoformat()

    assert _build_task().execute() == []
    mocks["sync"].assert_not_called()
    assert mocks["cache"].data[LOCK_CACHE_KEY] == AT_TARGET_HOUR.isoformat()


def test_execute_releases_lock_when_sync_raises(mocks):
    mocks["qs"].iterator.side_effect = RuntimeError("db down")

    with pytest.raises(RuntimeError):
        _build_task().execute()

    assert LOCK_CACHE_KEY not in mocks["cache"].data
