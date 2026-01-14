import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

from vitalstream.routes.vitalstream_api import CaretakerPortalAPI


class TestCaretakerPortalAPI:
    """Tests for the CaretakerPortalAPI class."""

    def create_api_instance(self, request_json: dict, secrets: dict) -> CaretakerPortalAPI:
        """Helper to create a CaretakerPortalAPI instance with mocked request and secrets."""
        api = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
        api.request = Mock()
        api.request.json.return_value = request_json
        api.secrets = secrets
        return api

    def test_authenticate_always_returns_true(self) -> None:
        """Test that authenticate always returns True regardless of credentials."""
        api = CaretakerPortalAPI.__new__(CaretakerPortalAPI)
        assert api.authenticate(Mock()) is True

    def test_index_rejects_unauthorized_serial_number(self) -> None:
        """Test that requests with unauthorized serial numbers are rejected."""
        api = self.create_api_instance(
            request_json={"sn": "UNAUTHORIZED123", "patid": "test-session-id"},
            secrets={"AUTHORIZED_SERIAL_NUMBERS": "abc123\ndef456"},
        )

        effects = api.index()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNAUTHORIZED

    def test_index_rejects_empty_serial_number(self) -> None:
        """Test that requests with empty serial numbers are rejected."""
        api = self.create_api_instance(
            request_json={"sn": "", "patid": "test-session-id"},
            secrets={"AUTHORIZED_SERIAL_NUMBERS": "abc123\ndef456"},
        )

        effects = api.index()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.UNAUTHORIZED

    @patch("vitalstream.routes.vitalstream_api.get_cache")
    def test_index_accepts_authorized_serial_number_no_session(self, mock_get_cache) -> None:
        """Test that authorized requests without an active session return accepted without broadcast."""
        mock_cache = Mock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        api = self.create_api_instance(
            request_json={"sn": "abc123", "patid": "nonexistent-session", "v1": {}, "spo2": {}},
            secrets={"AUTHORIZED_SERIAL_NUMBERS": "abc123\ndef456"},
        )

        effects = api.index()

        assert len(effects) == 1
        assert effects[0].status_code == HTTPStatus.ACCEPTED

    @patch("vitalstream.routes.vitalstream_api.get_cache")
    def test_index_accepts_and_broadcasts_with_active_session(self, mock_get_cache) -> None:
        """Test that authorized requests with an active session broadcast measurements."""
        mock_cache = Mock()
        mock_cache.get.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_get_cache.return_value = mock_cache

        api = self.create_api_instance(
            request_json={
                "sn": "abc123",
                "patid": "test-session-id",
                "v1": {
                    "0": {"ts": "2026-Jan-07 08:50:14 UTC", "hr": 72, "sys": 120, "dia": 80, "resp": 16},
                },
                "spo2": {
                    "0": {"ts": "2026-Jan-07 08:50:14 UTC", "v": 98},
                },
            },
            secrets={"AUTHORIZED_SERIAL_NUMBERS": "abc123\ndef456"},
        )

        effects = api.index()

        assert len(effects) == 2
        assert effects[0].status_code == HTTPStatus.ACCEPTED
        # Second effect is the broadcast
        broadcast_effect = effects[1]
        broadcast_payload = json.loads(broadcast_effect.payload)["data"]
        assert broadcast_payload["channel"] == "test_session_id"
        measurements = broadcast_payload["message"]["measurements"]
        assert "2026-01-07T08:50:14+00:00" in measurements
        assert measurements["2026-01-07T08:50:14+00:00"]["hr"] == 72
        assert measurements["2026-01-07T08:50:14+00:00"]["sys"] == 120
        assert measurements["2026-01-07T08:50:14+00:00"]["dia"] == 80
        assert measurements["2026-01-07T08:50:14+00:00"]["resp"] == 16
        assert measurements["2026-01-07T08:50:14+00:00"]["spo2"] == 98

    @patch("vitalstream.routes.vitalstream_api.get_cache")
    def test_index_handles_partial_measurements(self, mock_get_cache) -> None:
        """Test that partial measurements (missing some vitals) are handled correctly."""
        mock_cache = Mock()
        mock_cache.get.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_get_cache.return_value = mock_cache

        api = self.create_api_instance(
            request_json={
                "sn": "abc123",
                "patid": "test-session-id",
                "v1": {
                    "0": {"ts": "2026-Jan-07 08:50:14 UTC", "hr": 72},
                },
                "spo2": {},
            },
            secrets={"AUTHORIZED_SERIAL_NUMBERS": "abc123\ndef456"},
        )

        effects = api.index()

        assert len(effects) == 2
        broadcast_effect = effects[1]
        broadcast_payload = json.loads(broadcast_effect.payload)["data"]
        measurements = broadcast_payload["message"]["measurements"]
        assert measurements["2026-01-07T08:50:14+00:00"]["hr"] == 72
        assert "sys" not in measurements["2026-01-07T08:50:14+00:00"]

    def test_index_serial_number_case_insensitive(self) -> None:
        """Test that serial number comparison is case insensitive."""
        api = self.create_api_instance(
            request_json={"sn": "ABC123", "patid": "test-session-id"},
            secrets={"AUTHORIZED_SERIAL_NUMBERS": "abc123\ndef456"},
        )

        with patch("vitalstream.routes.vitalstream_api.get_cache") as mock_get_cache:
            mock_cache = Mock()
            mock_cache.get.return_value = None
            mock_get_cache.return_value = mock_cache

            effects = api.index()

            # Should be accepted (not unauthorized) because ABC123 lowercased matches abc123
            assert effects[0].status_code == HTTPStatus.ACCEPTED

    def test_convert_timestamp_to_iso8601(self) -> None:
        """Test timestamp conversion from device format to ISO8601."""
        api = CaretakerPortalAPI.__new__(CaretakerPortalAPI)

        result = api.convert_timestamp_to_iso8601("2026-Jan-07 08:50:14 UTC")

        assert result == "2026-01-07T08:50:14+00:00"

    def test_convert_timestamp_to_iso8601_different_months(self) -> None:
        """Test timestamp conversion works for different months."""
        api = CaretakerPortalAPI.__new__(CaretakerPortalAPI)

        assert api.convert_timestamp_to_iso8601("2026-Feb-15 12:30:00 UTC") == "2026-02-15T12:30:00+00:00"
        assert api.convert_timestamp_to_iso8601("2026-Dec-31 23:59:59 UTC") == "2026-12-31T23:59:59+00:00"
