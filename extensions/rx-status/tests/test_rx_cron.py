"""Tests for RxNotificationCron."""

from unittest.mock import MagicMock, patch

import arrow
import pytest

from rx_status.protocols.rx_cron import (
    CACHE_FIRED_KEY,
    CACHE_RULES_KEY,
    CACHE_STATUS_TIMESTAMPS_KEY,
    FIRED_CACHE_RETENTION_DAYS,
    RxNotificationCron,
)


def _make_cron(secrets=None):
    cron = RxNotificationCron.__new__(RxNotificationCron)
    cron.event = MagicMock()
    cron.secrets = secrets or {"INSTANCE_BASE_URL": "https://example.test"}
    return cron


class TestSchedule:
    def test_schedule_is_hourly_top_of_hour(self) -> None:
        assert RxNotificationCron.SCHEDULE == "0 * * * *"


class TestExecute:
    @patch("rx_status.protocols.rx_cron.get_cache")
    def test_no_rules_returns_empty(
        self, mock_get_cache: MagicMock, mock_cache: MagicMock
    ) -> None:
        mock_get_cache.return_value = mock_cache
        cron = _make_cron()

        result = cron.execute()

        assert result == []

    @patch("rx_status.protocols.rx_cron.get_cache")
    def test_only_immediate_rules_returns_empty(
        self,
        mock_get_cache: MagicMock,
        mock_cache: MagicMock,
        immediate_rule: dict,
    ) -> None:
        mock_cache._store[CACHE_RULES_KEY] = [immediate_rule]
        mock_get_cache.return_value = mock_cache
        cron = _make_cron()

        result = cron.execute()

        assert result == []

    @patch("rx_status.protocols.rx_cron.get_cache")
    @patch("rx_status.protocols.rx_cron.Prescription")
    @patch("rx_status.protocols.rx_cron.AddTask")
    @patch("rx_status.protocols.rx_cron.AddTaskComment")
    def test_duration_rule_fires_for_stale_rx(
        self,
        mock_comment: MagicMock,
        mock_add_task: MagicMock,
        mock_prescription_model: MagicMock,
        mock_get_cache: MagicMock,
        mock_cache: MagicMock,
        duration_rule: dict,
    ) -> None:
        mock_cache._store[CACHE_RULES_KEY] = [duration_rule]
        # Status timestamp is 48h ago → threshold (24h) is already past
        stale_since = arrow.utcnow().shift(hours=-48).isoformat()
        mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY] = {
            "rx-1": {"status": "pending", "since": stale_since}
        }
        mock_get_cache.return_value = mock_cache

        rx = MagicMock()
        rx.id = "rx-1"
        rx.patient.id = "patient-1"
        rx.note.dbid = 1
        mock_prescription_model.objects.filter.return_value.select_related.return_value = [rx]
        mock_prescription_model.objects.select_related.return_value.get.return_value = rx

        mock_add_task.return_value.apply.return_value = "task-effect"
        mock_comment.return_value.apply.return_value = "comment-effect"

        cron = _make_cron()
        result = cron.execute()

        assert "task-effect" in result
        assert f"rx-1_{duration_rule['id']}" in mock_cache._store[CACHE_FIRED_KEY]

    @patch("rx_status.protocols.rx_cron.get_cache")
    @patch("rx_status.protocols.rx_cron.Prescription")
    def test_duration_rule_skipped_when_not_yet_stale(
        self,
        mock_prescription_model: MagicMock,
        mock_get_cache: MagicMock,
        mock_cache: MagicMock,
        duration_rule: dict,
    ) -> None:
        mock_cache._store[CACHE_RULES_KEY] = [duration_rule]
        fresh_since = arrow.utcnow().shift(hours=-1).isoformat()
        mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY] = {
            "rx-1": {"status": "pending", "since": fresh_since}
        }
        mock_get_cache.return_value = mock_cache

        rx = MagicMock()
        rx.id = "rx-1"
        rx.patient.id = "patient-1"
        mock_prescription_model.objects.filter.return_value.select_related.return_value = [rx]

        cron = _make_cron()
        result = cron.execute()

        assert result == []

    @patch("rx_status.protocols.rx_cron.get_cache")
    @patch("rx_status.protocols.rx_cron.Prescription")
    def test_unknown_duration_unit_is_ignored(
        self,
        mock_prescription_model: MagicMock,
        mock_get_cache: MagicMock,
        mock_cache: MagicMock,
    ) -> None:
        mock_cache._store[CACHE_RULES_KEY] = [
            {
                "id": "r",
                "status": "pending",
                "duration_value": 1,
                "duration_unit": "w",
                "task_title": "weekly",
            }
        ]
        mock_get_cache.return_value = mock_cache
        cron = _make_cron()

        result = cron.execute()

        mock_prescription_model.objects.filter.assert_not_called()
        assert result == []


class TestStatusSince:
    def test_uses_cached_timestamp_when_status_matches(self) -> None:
        cron = _make_cron()
        timestamps = {"rx-1": {"status": "pending", "since": "2026-04-10T00:00:00+00:00"}}
        rx = MagicMock()

        result = cron._status_since(timestamps, "rx-1", "pending", rx)

        assert result == arrow.get("2026-04-10T00:00:00+00:00")

    def test_falls_back_to_modified_when_status_mismatch(self) -> None:
        cron = _make_cron()
        timestamps = {"rx-1": {"status": "error", "since": "2026-04-10T00:00:00+00:00"}}
        rx = MagicMock()
        rx.modified = "2026-04-01T00:00:00+00:00"

        result = cron._status_since(timestamps, "rx-1", "pending", rx)

        assert result == arrow.get("2026-04-01T00:00:00+00:00")

    def test_falls_back_to_modified_when_no_cache_entry(self) -> None:
        cron = _make_cron()
        rx = MagicMock()
        rx.modified = "2026-04-01T00:00:00+00:00"

        result = cron._status_since({}, "rx-1", "pending", rx)

        assert result == arrow.get("2026-04-01T00:00:00+00:00")

    def test_returns_none_when_no_cache_and_no_modified(self) -> None:
        cron = _make_cron()
        rx = MagicMock()
        rx.modified = None

        result = cron._status_since({}, "rx-1", "pending", rx)

        assert result is None


class TestFiredCachePruning:
    def test_prunes_old_entries(self, mock_cache: MagicMock) -> None:
        old = arrow.utcnow().shift(days=-(FIRED_CACHE_RETENTION_DAYS + 1)).isoformat()
        fresh = arrow.utcnow().shift(days=-1).isoformat()
        mock_cache._store[CACHE_FIRED_KEY] = {"stale_key": old, "fresh_key": fresh}

        cron = _make_cron()
        cron._prune_fired_cache(mock_cache)

        remaining = mock_cache._store[CACHE_FIRED_KEY]
        assert "fresh_key" in remaining
        assert "stale_key" not in remaining

    def test_no_writeback_when_nothing_to_prune(self, mock_cache: MagicMock) -> None:
        fresh = arrow.utcnow().shift(days=-1).isoformat()
        mock_cache._store[CACHE_FIRED_KEY] = {"k": fresh}

        cron = _make_cron()
        cron._prune_fired_cache(mock_cache)

        mock_cache.set.assert_not_called()

    def test_empty_cache_is_noop(self, mock_cache: MagicMock) -> None:
        cron = _make_cron()

        cron._prune_fired_cache(mock_cache)

        mock_cache.set.assert_not_called()


class TestImmutableMarkFired:
    def test_does_not_mutate_original_map(self, mock_cache: MagicMock) -> None:
        original = {"k0": "2026-01-01T00:00:00+00:00"}
        mock_cache._store[CACHE_FIRED_KEY] = original
        cron = _make_cron()

        cron._mark_fired(mock_cache, "rx-new", {"id": "rule-new"})

        assert original == {"k0": "2026-01-01T00:00:00+00:00"}
        assert "rx-new_rule-new" in mock_cache._store[CACHE_FIRED_KEY]
