"""Tests for the Candid nightly sync cron."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from candid.cron.nightly_sync import (
    BATCH_TIME_BUDGET,
    CURSOR_CACHE_KEY,
    DEFAULT_START_HOUR,
    LAST_START_CACHE_KEY,
    LOCK_CACHE_KEY,
    START_HOUR_VARIABLE,
    STATS_KEY,
    NightlyCandidSync,
    start_hour,
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
        # Most tests keep durable state and the lock in one dict; the PLUGIN-501
        # tests below split them to model the cache losing keys.
        patch("candid.cron.nightly_sync.SyncState", return_value=cache),
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
    # A skipped start hour must not use up today's start (it would block the day).
    assert LAST_START_CACHE_KEY not in mocks["cache"].data


def test_execute_releases_lock_when_sync_raises(mocks):
    mocks["qs"].iterator.side_effect = RuntimeError("db down")

    with pytest.raises(RuntimeError):
        _build_task().execute()

    assert LOCK_CACHE_KEY not in mocks["cache"].data


# --- CANDID_SYNC_START_HOUR (the instance's own start hour) -------------------


# 04:00 UTC == 21:00 US/Pacific (PDT); 09:00 UTC == 02:00 US/Pacific.
AT_21_PACIFIC = datetime(2026, 6, 3, 4, 0, tzinfo=UTC)
AT_2_PACIFIC = datetime(2026, 6, 3, 9, 0, tzinfo=UTC)


def _build_task_with(tz: str, **secrets) -> NightlyCandidSync:
    return NightlyCandidSync(
        event=MagicMock(),
        secrets={**MOCK_SECRETS, **secrets},
        environment={"INSTALLATION_TIME_ZONE": tz},
    )


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_start_hour_defaults_to_2_when_unset(raw):
    secrets = {} if raw is None else {START_HOUR_VARIABLE: raw}
    assert start_hour(secrets) == DEFAULT_START_HOUR == 2


@pytest.mark.parametrize("raw,expected", [("0", 0), ("21", 21), (" 23 ", 23), (5, 5)])
def test_start_hour_reads_a_valid_hour(raw, expected):
    assert start_hour({START_HOUR_VARIABLE: raw}) == expected


@pytest.mark.parametrize("raw", ["24", "-1", "9pm", "2.5", "midnight"])
def test_start_hour_falls_back_to_2_and_warns_on_a_bad_value(raw):
    with patch("candid.cron.nightly_sync.log") as mock_log:
        assert start_hour({START_HOUR_VARIABLE: raw}) == 2
    mock_log.warning.assert_called_once()


def test_execute_starts_at_the_configured_hour(mocks):
    mocks["dt"].now.return_value = AT_21_PACIFIC
    mocks["qs"].iterator.return_value = [_claim("c1")]
    mocks["sync"].return_value = []

    _build_task_with("US/Pacific", CANDID_SYNC_START_HOUR="21").execute()

    mocks["sync"].assert_called_once()


def test_execute_no_longer_starts_at_2_once_an_hour_is_set(mocks):
    mocks["dt"].now.return_value = AT_2_PACIFIC

    assert _build_task_with("US/Pacific", CANDID_SYNC_START_HOUR="21").execute() == []
    mocks["sync"].assert_not_called()


def test_execute_still_starts_at_2_with_no_hour_set(mocks):
    mocks["dt"].now.return_value = AT_2_PACIFIC
    mocks["qs"].iterator.return_value = [_claim("c1")]
    mocks["sync"].return_value = []

    _build_task_with("US/Pacific").execute()

    mocks["sync"].assert_called_once()


def test_a_running_cycle_continues_whatever_the_start_hour(mocks):
    mocks["cache"].data[CURSOR_CACHE_KEY] = "c0"
    mocks["dt"].now.return_value = AT_2_PACIFIC
    mocks["qs"].iterator.return_value = [_claim("c1")]
    mocks["sync"].return_value = []

    _build_task_with("US/Pacific", CANDID_SYNC_START_HOUR="21").execute()

    mocks["sync"].assert_called_once()


@pytest.mark.parametrize("raw", ["²", "٢", "1²", "123"])
def test_start_hour_rejects_non_ascii_digits_without_crashing(raw):
    with patch("candid.cron.nightly_sync.log"):
        assert start_hour({START_HOUR_VARIABLE: raw}) == 2


def test_only_one_cycle_starts_per_local_day(mocks):

    mocks["qs"].iterator.return_value = [_claim("c1")]
    mocks["sync"].return_value = []
    task = _build_task()

    task.execute()  # starts and completes today's cycle (cursor cleared)
    assert mocks["cache"].data[LAST_START_CACHE_KEY] == "2026-06-03"
    task.execute()  # same local day and hour (e.g. the repeated fall-back hour)

    assert mocks["sync"].call_count == 1


def test_a_new_day_starts_a_new_cycle(mocks):

    mocks["cache"].data[LAST_START_CACHE_KEY] = "2026-06-02"
    mocks["qs"].iterator.return_value = [_claim("c1")]
    mocks["sync"].return_value = []

    _build_task().execute()

    mocks["sync"].assert_called_once()


# --- PLUGIN-501: the cursor survives the plugin cache losing keys ------------


def test_cursor_survives_the_cache_being_culled_between_ticks(mocks):
    """The shared cache can drop candid's keys between ticks; the cycle must go on."""
    durable = FakeCache()
    mocks["sync"].side_effect = lambda claim, secrets: [f"effect-{claim.id}"]
    with patch("candid.cron.nightly_sync.SyncState", return_value=durable):
        mocks["qs"].iterator.return_value = [_claim("a"), _claim("b"), _claim("c")]
        with patch("candid.cron.nightly_sync.MAX_CLAIMS_PER_BATCH", 2):
            assert _build_task().execute() == ["effect-a", "effect-b"]
        assert durable.data[CURSOR_CACHE_KEY] == "b"
        assert CURSOR_CACHE_KEY not in mocks["cache"].data

        mocks["cache"].data.clear()  # the platform culls the shared cache
        mocks["dt"].now.return_value = OFF_TARGET_HOUR  # next hourly tick
        mocks["qs"].iterator.return_value = [_claim("c")]

        assert _build_task().execute() == ["effect-c"]

    mocks["qs"].filter.assert_called_with(id__gt="b")
    assert CURSOR_CACHE_KEY not in durable.data


def test_last_start_date_is_kept_in_durable_state(mocks):

    durable = FakeCache()
    mocks["qs"].iterator.return_value = [_claim("c1")]
    mocks["sync"].return_value = []
    with patch("candid.cron.nightly_sync.SyncState", return_value=durable):
        _build_task().execute()
        mocks["cache"].data.clear()
        _build_task().execute()  # same local day and hour, cache emptied

    assert durable.data[LAST_START_CACHE_KEY] == "2026-06-03"
    assert mocks["sync"].call_count == 1


# --- Cycle totals and the end-of-cycle path ------------------------------------


def test_cycle_completes_after_backlog_with_totals_logged(mocks):
    """Three hourly batches over a backlog, then "cycle complete" with totals."""
    mocks["sync"].side_effect = lambda claim, secrets: (
        (_ for _ in ()).throw(RuntimeError("bad claim"))
        if claim.id == "b"
        else [f"effect-{claim.id}"]
    )

    with (
        patch("candid.cron.nightly_sync.MAX_CLAIMS_PER_BATCH", 2),
        patch("candid.cron.nightly_sync.log") as mock_log,
    ):
        mocks["qs"].iterator.return_value = [_claim("a"), _claim("b"), _claim("c")]
        assert _build_task().execute() == ["effect-a"]
        assert mocks["cache"].data[CURSOR_CACHE_KEY] == "b"
        assert mocks["cache"].data[STATS_KEY] == {
            "processed": 2,
            "synced": 1,
            "failed": 1,
            "batches": 1,
        }
        assert "(1 failed), continuing next hour" in mock_log.info.call_args.args[0]

        mocks["dt"].now.return_value = OFF_TARGET_HOUR
        mocks["qs"].iterator.return_value = [_claim("c"), _claim("d"), _claim("e")]
        assert _build_task().execute() == ["effect-c", "effect-d"]
        assert mocks["cache"].data[CURSOR_CACHE_KEY] == "d"

        mocks["qs"].iterator.return_value = [_claim("e")]
        assert _build_task().execute() == ["effect-e"]

    # The failed claim was tried once; the cursor moved past it
    assert [c.args[0].id for c in mocks["sync"].call_args_list] == [
        "a",
        "b",
        "c",
        "d",
        "e",
    ]
    assert CURSOR_CACHE_KEY not in mocks["cache"].data
    assert STATS_KEY not in mocks["cache"].data
    final = mock_log.info.call_args.args[0]
    assert "synced 1/1 claims (0 failed), cycle complete" in final
    assert "4/5 claims synced, 1 failed, over 3 batches" in final


def test_new_cycle_clears_stale_totals(mocks):
    """Totals left by a cycle that never finished don't leak into the next one."""
    mocks["cache"].data[STATS_KEY] = {
        "processed": 99,
        "synced": 9,
        "failed": 90,
        "batches": 7,
    }
    mocks["qs"].iterator.return_value = [_claim("a")]
    mocks["sync"].return_value = ["effect-a"]

    with patch("candid.cron.nightly_sync.log") as mock_log:
        _build_task().execute()

    assert (
        "1/1 claims synced, 0 failed, over 1 batches" in mock_log.info.call_args.args[0]
    )


def test_malformed_totals_are_ignored(mocks):
    mocks["dt"].now.return_value = OFF_TARGET_HOUR
    mocks["cache"].data[CURSOR_CACHE_KEY] = "a"
    mocks["cache"].data[STATS_KEY] = "garbage"
    mocks["qs"].iterator.return_value = [_claim("b")]
    mocks["sync"].return_value = ["effect-b"]

    with patch("candid.cron.nightly_sync.log") as mock_log:
        _build_task().execute()

    assert (
        "1/1 claims synced, 0 failed, over 1 batches" in mock_log.info.call_args.args[0]
    )
