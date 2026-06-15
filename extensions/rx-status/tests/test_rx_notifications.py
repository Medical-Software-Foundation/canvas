"""Tests for RxNotificationProtocol."""

from unittest.mock import MagicMock, patch

import pytest

from rx_status.protocols.rx_notifications import (
    CACHE_FIRED_KEY,
    CACHE_RULES_KEY,
    CACHE_STATUS_TIMESTAMPS_KEY,
    EVENT_STATUS_MAP,
    RxNotificationProtocol,
)


def _make_protocol(event, secrets=None):
    protocol = RxNotificationProtocol.__new__(RxNotificationProtocol)
    protocol.event = event
    protocol.secrets = secrets or {"INSTANCE_BASE_URL": "https://example.test"}
    return protocol


class TestEventMapping:
    def test_event_map_covers_12_events(self) -> None:
        assert len(EVENT_STATUS_MAP) == 12

    def test_event_map_contains_expected_statuses(self) -> None:
        assert "pending" in EVENT_STATUS_MAP.values()
        assert "error" in EVENT_STATUS_MAP.values()
        assert "ultimately-accepted" in EVENT_STATUS_MAP.values()


class TestCompute:
    @patch("rx_status.protocols.rx_notifications.EventType")
    @patch("rx_status.protocols.rx_notifications.get_cache")
    def test_unknown_event_returns_empty(
        self, mock_get_cache: MagicMock, mock_event_type: MagicMock, mock_event: MagicMock
    ) -> None:
        mock_event_type.Name.return_value = "UNMAPPED_EVENT"
        protocol = _make_protocol(mock_event)

        result = protocol.compute()

        assert result == []
        mock_get_cache.assert_not_called()

    @patch("rx_status.protocols.rx_notifications.EventType")
    @patch("rx_status.protocols.rx_notifications.get_cache")
    def test_no_rules_configured_returns_empty(
        self,
        mock_get_cache: MagicMock,
        mock_event_type: MagicMock,
        mock_event: MagicMock,
        mock_cache: MagicMock,
    ) -> None:
        mock_event_type.Name.return_value = "PRESCRIPTION_ERRORED"
        # Patch the EVENT_STATUS_MAP lookup via monkeypatch
        with patch.dict(
            "rx_status.protocols.rx_notifications.EVENT_STATUS_MAP",
            {"PRESCRIPTION_ERRORED": "error"},
            clear=False,
        ):
            mock_get_cache.return_value = mock_cache
            protocol = _make_protocol(mock_event)

            result = protocol.compute()

        assert result == []

    @patch("rx_status.protocols.rx_notifications.EventType")
    @patch("rx_status.protocols.rx_notifications.get_cache")
    @patch("rx_status.protocols.rx_notifications.AddTask")
    @patch("rx_status.protocols.rx_notifications.AddTaskComment")
    @patch("rx_status.protocols.rx_notifications.Prescription")
    def test_immediate_rule_fires_and_marks_dedup(
        self,
        mock_prescription_model: MagicMock,
        mock_add_task_comment: MagicMock,
        mock_add_task: MagicMock,
        mock_get_cache: MagicMock,
        mock_event_type: MagicMock,
        mock_event: MagicMock,
        mock_cache: MagicMock,
        immediate_rule: dict,
    ) -> None:
        mock_event_type.Name.return_value = "PRESCRIPTION_ERRORED"
        mock_cache._store[CACHE_RULES_KEY] = [immediate_rule]
        mock_get_cache.return_value = mock_cache

        rx = MagicMock()
        rx.note.dbid = 99
        mock_prescription_model.objects.select_related.return_value.get.return_value = rx

        mock_add_task.return_value.apply.return_value = "task-effect"
        mock_add_task_comment.return_value.apply.return_value = "comment-effect"

        with patch.dict(
            "rx_status.protocols.rx_notifications.EVENT_STATUS_MAP",
            {"PRESCRIPTION_ERRORED": "error"},
            clear=False,
        ):
            protocol = _make_protocol(mock_event)
            result = protocol.compute()

        assert "task-effect" in result
        assert "comment-effect" in result
        fired = mock_cache._store.get(CACHE_FIRED_KEY, {})
        assert "rx-abc-123_rule-immediate" in fired

    @patch("rx_status.protocols.rx_notifications.EventType")
    @patch("rx_status.protocols.rx_notifications.get_cache")
    def test_duration_rule_skipped_by_event_handler(
        self,
        mock_get_cache: MagicMock,
        mock_event_type: MagicMock,
        mock_event: MagicMock,
        mock_cache: MagicMock,
        duration_rule: dict,
    ) -> None:
        mock_event_type.Name.return_value = "PRESCRIPTION_PENDING"
        mock_cache._store[CACHE_RULES_KEY] = [duration_rule]
        mock_get_cache.return_value = mock_cache

        with patch.dict(
            "rx_status.protocols.rx_notifications.EVENT_STATUS_MAP",
            {"PRESCRIPTION_PENDING": "pending"},
            clear=False,
        ):
            protocol = _make_protocol(mock_event)
            result = protocol.compute()

        assert result == []

    @patch("rx_status.protocols.rx_notifications.EventType")
    @patch("rx_status.protocols.rx_notifications.get_cache")
    def test_dedup_prevents_refire(
        self,
        mock_get_cache: MagicMock,
        mock_event_type: MagicMock,
        mock_event: MagicMock,
        mock_cache: MagicMock,
        immediate_rule: dict,
    ) -> None:
        mock_event_type.Name.return_value = "PRESCRIPTION_ERRORED"
        mock_cache._store[CACHE_RULES_KEY] = [immediate_rule]
        mock_cache._store[CACHE_FIRED_KEY] = {
            "rx-abc-123_rule-immediate": "2026-04-15T00:00:00+00:00"
        }
        mock_get_cache.return_value = mock_cache

        with patch.dict(
            "rx_status.protocols.rx_notifications.EVENT_STATUS_MAP",
            {"PRESCRIPTION_ERRORED": "error"},
            clear=False,
        ):
            protocol = _make_protocol(mock_event)
            result = protocol.compute()

        assert result == []


class TestStatusTimestampRecording:
    def test_timestamp_recorded_on_new_status(
        self, mock_cache: MagicMock
    ) -> None:
        protocol = _make_protocol(MagicMock())

        protocol._record_status_timestamp(mock_cache, "rx-1", "pending")

        stored = mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY]
        assert stored["rx-1"]["status"] == "pending"
        assert "since" in stored["rx-1"]

    def test_timestamp_not_overwritten_for_same_status(
        self, mock_cache: MagicMock
    ) -> None:
        mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY] = {
            "rx-1": {"status": "pending", "since": "2026-01-01T00:00:00+00:00"}
        }
        protocol = _make_protocol(MagicMock())

        protocol._record_status_timestamp(mock_cache, "rx-1", "pending")

        assert (
            mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY]["rx-1"]["since"]
            == "2026-01-01T00:00:00+00:00"
        )

    def test_timestamp_replaced_on_status_change(
        self, mock_cache: MagicMock
    ) -> None:
        mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY] = {
            "rx-1": {"status": "pending", "since": "2026-01-01T00:00:00+00:00"}
        }
        protocol = _make_protocol(MagicMock())

        protocol._record_status_timestamp(mock_cache, "rx-1", "error")

        assert (
            mock_cache._store[CACHE_STATUS_TIMESTAMPS_KEY]["rx-1"]["status"] == "error"
        )


class TestImmutability:
    def test_mark_fired_does_not_mutate_original(self, mock_cache: MagicMock) -> None:
        original = {"rx-0_rule-0": "2026-01-01T00:00:00+00:00"}
        mock_cache._store[CACHE_FIRED_KEY] = original
        protocol = _make_protocol(MagicMock())

        protocol._mark_fired(mock_cache, "rx-1", {"id": "rule-1"})

        assert original == {"rx-0_rule-0": "2026-01-01T00:00:00+00:00"}
        assert "rx-1_rule-1" in mock_cache._store[CACHE_FIRED_KEY]


class TestNoteLink:
    @patch("rx_status.protocols.rx_notifications.Prescription")
    def test_note_link_built_from_secret(
        self, mock_prescription_model: MagicMock
    ) -> None:
        rx = MagicMock()
        rx.note.dbid = 777
        mock_prescription_model.objects.select_related.return_value.get.return_value = rx

        protocol = _make_protocol(
            MagicMock(), secrets={"INSTANCE_BASE_URL": "https://host.test/"}
        )

        result = protocol._get_note_link("rx-1", "patient-1")

        assert result == "https://host.test/patient/patient-1/note/777"

    @patch("rx_status.protocols.rx_notifications.Prescription")
    def test_note_link_none_when_prescription_missing(
        self, mock_prescription_model: MagicMock
    ) -> None:
        from canvas_sdk.v1.data.prescription import Prescription

        mock_prescription_model.DoesNotExist = Prescription.DoesNotExist
        mock_prescription_model.objects.select_related.return_value.get.side_effect = (
            Prescription.DoesNotExist
        )

        protocol = _make_protocol(MagicMock())

        result = protocol._get_note_link("rx-1", "patient-1")

        assert result is None
