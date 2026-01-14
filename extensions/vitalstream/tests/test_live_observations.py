from unittest.mock import Mock, patch

import pytest

from vitalstream.channels.live_observations import LiveObservationsChannel


class TestLiveObservationsChannel:
    """Tests for the LiveObservationsChannel class."""

    def create_channel_instance(self, channel_name: str, logged_in_user: dict) -> LiveObservationsChannel:
        """Helper to create a LiveObservationsChannel instance with mocked websocket."""
        channel = LiveObservationsChannel.__new__(LiveObservationsChannel)
        channel.websocket = Mock()
        channel.websocket.channel = channel_name
        channel.websocket.logged_in_user = logged_in_user
        return channel

    @patch("vitalstream.channels.live_observations.get_cache")
    def test_authenticate_returns_true_for_valid_session_and_staff(self, mock_get_cache) -> None:
        """Test that authentication succeeds when session exists and user is Staff."""
        mock_cache = Mock()
        mock_cache.get.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_get_cache.return_value = mock_cache

        channel = self.create_channel_instance(
            channel_name="test_session_id",
            logged_in_user={"type": "Staff", "id": "staff-456"},
        )

        result = channel.authenticate()

        assert result is True
        mock_cache.get.assert_called_once_with("session_id:test-session-id")

    @patch("vitalstream.channels.live_observations.get_cache")
    def test_authenticate_returns_false_when_session_not_found(self, mock_get_cache) -> None:
        """Test that authentication fails when session doesn't exist."""
        mock_cache = Mock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        channel = self.create_channel_instance(
            channel_name="nonexistent_session",
            logged_in_user={"type": "Staff", "id": "staff-456"},
        )

        result = channel.authenticate()

        assert result is False

    @patch("vitalstream.channels.live_observations.get_cache")
    def test_authenticate_returns_false_when_user_is_not_staff(self, mock_get_cache) -> None:
        """Test that authentication fails when user is not Staff."""
        mock_cache = Mock()
        mock_cache.get.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_get_cache.return_value = mock_cache

        channel = self.create_channel_instance(
            channel_name="test_session_id",
            logged_in_user={"type": "Patient", "id": "patient-789"},
        )

        result = channel.authenticate()

        assert result is False

    @patch("vitalstream.channels.live_observations.get_cache")
    def test_authenticate_returns_false_when_session_missing_and_not_staff(self, mock_get_cache) -> None:
        """Test that authentication fails when both conditions are not met."""
        mock_cache = Mock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        channel = self.create_channel_instance(
            channel_name="nonexistent_session",
            logged_in_user={"type": "Patient", "id": "patient-789"},
        )

        result = channel.authenticate()

        assert result is False

    @patch("vitalstream.channels.live_observations.get_cache")
    def test_authenticate_converts_underscores_to_hyphens_in_channel_name(self, mock_get_cache) -> None:
        """Test that underscores in channel name are converted to hyphens for session lookup."""
        mock_cache = Mock()
        mock_cache.get.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_get_cache.return_value = mock_cache

        channel = self.create_channel_instance(
            channel_name="abc_def_123_456",
            logged_in_user={"type": "Staff", "id": "staff-456"},
        )

        channel.authenticate()

        # Session key should have hyphens instead of underscores
        mock_cache.get.assert_called_once_with("session_id:abc-def-123-456")

    @patch("vitalstream.channels.live_observations.get_cache")
    def test_authenticate_handles_uppercase_channel_name(self, mock_get_cache) -> None:
        """Test that channel name is lowercased before session lookup."""
        mock_cache = Mock()
        mock_cache.get.return_value = {"note_id": "note-123", "staff_id": "staff-456"}
        mock_get_cache.return_value = mock_cache

        channel = self.create_channel_instance(
            channel_name="TEST_SESSION_ID",
            logged_in_user={"type": "Staff", "id": "staff-456"},
        )

        channel.authenticate()

        # Session key should be lowercased
        mock_cache.get.assert_called_once_with("session_id:test-session-id")
