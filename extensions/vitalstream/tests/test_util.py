from vitalstream.util import session_key


class TestSessionKey:
    """Tests for the session_key function."""

    def test_session_key_returns_formatted_string(self) -> None:
        """Test that session_key returns the correct format."""
        result = session_key("abc-123")
        assert result == "session_id:abc-123"

    def test_session_key_with_uuid(self) -> None:
        """Test session_key with a UUID-style session ID."""
        result = session_key("550e8400-e29b-41d4-a716-446655440000")
        assert result == "session_id:550e8400-e29b-41d4-a716-446655440000"

    def test_session_key_with_empty_string(self) -> None:
        """Test session_key with an empty string."""
        result = session_key("")
        assert result == "session_id:"

    def test_session_key_preserves_case(self) -> None:
        """Test that session_key preserves the case of the input."""
        result = session_key("ABC-123")
        assert result == "session_id:ABC-123"
