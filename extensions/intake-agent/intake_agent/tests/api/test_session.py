import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from intake_agent.api import session


# Load the schema content once for all tests
_schema_path = os.path.join(
    os.path.dirname(__file__), "..", "..", "intake_agent", "schemas", "intake_session.json"
)
with open(_schema_path) as f:
    _SCHEMA_CONTENT = f.read()


# No longer need to mock render_to_string since we're not loading the schema


class TestSession:
    """Unit tests for session management module."""

    def test_generate_session_id_returns_32_char_hex(self):
        """Test that generate_session_id returns a 32-character hex string."""
        # Act
        session_id = session.generate_session_id()

        # Assert
        assert isinstance(session_id, str)
        assert len(session_id) == 32
        assert all(c in "0123456789abcdef" for c in session_id)

    def test_generate_session_id_is_unique(self):
        """Test that generate_session_id produces unique IDs."""
        # Act
        session_id1 = session.generate_session_id()
        session_id2 = session.generate_session_id()

        # Assert
        assert session_id1 != session_id2

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.generate_session_id")
    @patch("intake_agent.api.session.log")
    def test_create_session_returns_session_data(
        self, mock_log, mock_generate_id, mock_get_cache
    ):
        """Test that create_session returns properly structured session data."""
        # Arrange
        # Use a valid 32-character hex session ID
        mock_generate_id.return_value = "a1b2c3d4e5f67890a1b2c3d4e5f67890"
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        result = session.create_session()

        # Assert
        assert result["session_id"] == "a1b2c3d4e5f67890a1b2c3d4e5f67890"
        assert "created_at" in result
        assert "updated_at" in result
        assert result["messages"] == []
        assert result["collected_data"]["first_name"] is None
        assert result["collected_data"]["last_name"] is None
        assert result["collected_data"]["email"] is None
        assert result["collected_data"]["phone"] is None
        assert result["status"] == "active"

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.generate_session_id")
    def test_create_session_stores_in_cache(self, mock_generate_id, mock_get_cache):
        """Test that create_session stores session data in cache."""
        # Arrange
        # Use a valid 32-character hex session ID
        mock_generate_id.return_value = "b2c3d4e5f67890a1b2c3d4e5f67890a1"
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache

        # Act
        session.create_session()

        # Assert
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "intake_session:b2c3d4e5f67890a1b2c3d4e5f67890a1"
        assert call_args[1]["timeout_seconds"] == 3600  # 1 hour

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.log")
    def test_get_session_returns_session_data(self, mock_log, mock_get_cache):
        """Test that get_session retrieves session data from cache."""
        # Arrange
        mock_cache = MagicMock()
        expected_data = {
            "session_id": "test-session",
            "messages": [],
            "status": "active",
        }
        mock_cache.get.return_value = expected_data
        mock_get_cache.return_value = mock_cache

        # Act
        result = session.get_session("test-session")

        # Assert
        assert result == expected_data
        mock_cache.get.assert_called_once_with("intake_session:test-session")
        mock_log.info.assert_called()

    @patch("intake_agent.api.session.get_cache")
    @patch("intake_agent.api.session.log")
    def test_get_session_returns_none_when_not_found(self, mock_log, mock_get_cache):
        """Test that get_session returns None when session doesn't exist."""
        # Arrange
        mock_cache = MagicMock()
        mock_cache.get.return_value = None
        mock_get_cache.return_value = mock_cache

        # Act
        result = session.get_session("nonexistent-session")

        # Assert
        assert result is None
        mock_log.warning.assert_called()

    @patch("intake_agent.api.session.get_cache")
    def test_update_session_stores_updated_data(self, mock_get_cache):
        """Test that update_session stores updated session data."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache
        # Use valid 32-character hex session ID and complete session data
        session_data = {
            "session_id": "c3d4e5f67890a1b2c3d4e5f67890a1b2",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "status": "active",
        }

        # Act
        session.update_session("c3d4e5f67890a1b2c3d4e5f67890a1b2", session_data)

        # Assert
        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "intake_session:c3d4e5f67890a1b2c3d4e5f67890a1b2"
        assert "updated_at" in call_args[0][1]
        assert call_args[1]["timeout_seconds"] == 3600

    @patch("intake_agent.api.session.get_cache")
    def test_update_session_updates_timestamp(self, mock_get_cache):
        """Test that update_session updates the updated_at timestamp."""
        # Arrange
        mock_cache = MagicMock()
        mock_get_cache.return_value = mock_cache
        old_timestamp = "2025-01-01T00:00:00Z"
        # Use valid 32-character hex session ID and complete session data
        session_data = {
            "session_id": "d4e5f67890a1b2c3d4e5f67890a1b2c3",
            "created_at": old_timestamp,
            "updated_at": old_timestamp,
            "messages": [],
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": None,
                "date_of_birth": None,
                "reason_for_visit": None,
            },
            "status": "active",
        }

        # Act
        session.update_session("d4e5f67890a1b2c3d4e5f67890a1b2c3", session_data)

        # Assert
        stored_data = mock_cache.set.call_args[0][1]
        assert stored_data["updated_at"] != old_timestamp

    @patch("intake_agent.api.session.update_session")
    @patch("intake_agent.api.session.get_session")
    def test_add_message_adds_user_message(self, mock_get_session, mock_update_session):
        """Test that add_message adds a user message to the session."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "messages": [],
        }

        # Act
        result = session.add_message("test-session", "user", "Hello, I need help")

        # Assert
        assert result is not None
        mock_update_session.assert_called_once()
        stored_session = mock_update_session.call_args[0][1]
        assert len(stored_session["messages"]) == 1
        assert stored_session["messages"][0]["role"] == "user"
        assert stored_session["messages"][0]["content"] == "Hello, I need help"
        assert "timestamp" in stored_session["messages"][0]

    @patch("intake_agent.api.session.update_session")
    @patch("intake_agent.api.session.get_session")
    def test_add_message_adds_agent_message(self, mock_get_session, mock_update_session):
        """Test that add_message adds an agent message to the session."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "messages": [],
        }

        # Act
        result = session.add_message("test-session", "agent", "How can I help you?")

        # Assert
        assert result is not None
        stored_session = mock_update_session.call_args[0][1]
        assert len(stored_session["messages"]) == 1
        assert stored_session["messages"][0]["role"] == "agent"
        assert stored_session["messages"][0]["content"] == "How can I help you?"

    @patch("intake_agent.api.session.get_session")
    def test_add_message_returns_none_for_invalid_session(self, mock_get_session):
        """Test that add_message returns None when session doesn't exist."""
        # Arrange
        mock_get_session.return_value = None

        # Act
        result = session.add_message("nonexistent", "user", "Hello")

        # Assert
        assert result is None

    @patch("intake_agent.api.session.update_session")
    @patch("intake_agent.api.session.get_session")
    def test_add_message_appends_to_existing_messages(
        self, mock_get_session, mock_update_session
    ):
        """Test that add_message appends to existing messages."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "messages": [
                {"role": "agent", "content": "Hello", "timestamp": "2025-01-01T00:00:00Z"}
            ],
        }

        # Act
        session.add_message("test-session", "user", "Hi there")

        # Assert
        stored_session = mock_update_session.call_args[0][1]
        assert len(stored_session["messages"]) == 2
        assert stored_session["messages"][1]["content"] == "Hi there"

    @patch("intake_agent.api.session.update_session")
    @patch("intake_agent.api.session.get_session")
    def test_update_collected_data_updates_field(
        self, mock_get_session, mock_update_session
    ):
        """Test that update_collected_data updates a specific field."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": None,
            },
        }

        # Act
        result = session.update_collected_data("test-session", "first_name", "John")

        # Assert
        assert result is not None
        stored_session = mock_update_session.call_args[0][1]
        assert stored_session["collected_data"]["first_name"] == "John"

    @patch("intake_agent.api.session.get_session")
    def test_update_collected_data_returns_none_for_invalid_session(
        self, mock_get_session
    ):
        """Test that update_collected_data returns None for invalid session."""
        # Arrange
        mock_get_session.return_value = None

        # Act
        result = session.update_collected_data("nonexistent", "first_name", "John")

        # Assert
        assert result is None

    @patch("intake_agent.api.session.update_session")
    @patch("intake_agent.api.session.get_session")
    @patch("intake_agent.api.session.log")
    def test_update_collected_data_warns_for_invalid_field(
        self, mock_log, mock_get_session, mock_update_session
    ):
        """Test that update_collected_data logs warning for invalid field."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "collected_data": {
                "first_name": None,
                "last_name": None,
                "email": None,
                "phone": None,
            },
        }

        # Act
        session.update_collected_data("test-session", "invalid_field", "value")

        # Assert
        mock_log.warning.assert_called()
        # Should not call update_session since field is invalid
        mock_update_session.assert_not_called()

    @patch("intake_agent.api.session.update_session")
    @patch("intake_agent.api.session.get_session")
    def test_complete_session_marks_as_completed(
        self, mock_get_session, mock_update_session
    ):
        """Test that complete_session marks session as completed."""
        # Arrange
        mock_get_session.return_value = {
            "session_id": "test-session",
            "status": "active",
        }

        # Act
        result = session.complete_session("test-session")

        # Assert
        assert result is not None
        stored_session = mock_update_session.call_args[0][1]
        assert stored_session["status"] == "completed"

    @patch("intake_agent.api.session.get_session")
    def test_complete_session_returns_none_for_invalid_session(self, mock_get_session):
        """Test that complete_session returns None for invalid session."""
        # Arrange
        mock_get_session.return_value = None

        # Act
        result = session.complete_session("nonexistent")

        # Assert
        assert result is None

    @patch("intake_agent.api.session.log")
    def test_all_functions_use_correct_cache_key_format(self, mock_log):
        """Test that all functions use the correct cache key format."""
        # The cache key format should be "intake_session:{session_id}"
        # This is implicitly tested by the other tests, but we verify the pattern

        # Arrange & Act & Assert
        with patch("intake_agent.api.session.get_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_get_cache.return_value = mock_cache

            # Test get_session
            session.get_session("test-123")
            assert mock_cache.get.call_args[0][0] == "intake_session:test-123"

            # Test update_session
            mock_cache.reset_mock()
            # Use valid 32-character hex session ID and complete session data
            valid_session_data = {
                "session_id": "e5f67890a1b2c3d4e5f67890a1b2c3d4",
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
                "messages": [],
                "collected_data": {
                    "first_name": None,
                    "last_name": None,
                    "email": None,
                    "phone": None,
                    "date_of_birth": None,
                    "reason_for_visit": None,
                },
                "status": "active",
            }
            session.update_session("e5f67890a1b2c3d4e5f67890a1b2c3d4", valid_session_data)
            assert mock_cache.set.call_args[0][0] == "intake_session:e5f67890a1b2c3d4e5f67890a1b2c3d4"
