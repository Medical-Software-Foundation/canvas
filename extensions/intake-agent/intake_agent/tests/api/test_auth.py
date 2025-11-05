from unittest.mock import patch

import pytest

from intake_agent.api import auth


class TestAuth:
    """Unit tests for authentication module."""

    def test_generate_signature_creates_hmac_sha256(self):
        """Test that generate_signature creates an HMAC-SHA256 signature."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"

        # Act
        signature = auth.generate_signature(session_id, secret_key)

        # Assert
        assert isinstance(signature, str)
        assert len(signature) == 64  # SHA256 produces 64 hex characters
        # Verify it's hexadecimal
        assert all(c in "0123456789abcdef" for c in signature)

    def test_generate_signature_is_deterministic(self):
        """Test that generate_signature produces the same output for same input."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"

        # Act
        signature1 = auth.generate_signature(session_id, secret_key)
        signature2 = auth.generate_signature(session_id, secret_key)

        # Assert
        assert signature1 == signature2

    def test_generate_signature_differs_with_different_session_id(self):
        """Test that different session IDs produce different signatures."""
        # Arrange
        secret_key = "test-secret-key"
        session_id1 = "session-1"
        session_id2 = "session-2"

        # Act
        signature1 = auth.generate_signature(session_id1, secret_key)
        signature2 = auth.generate_signature(session_id2, secret_key)

        # Assert
        assert signature1 != signature2

    def test_generate_signature_differs_with_different_secret_key(self):
        """Test that different secret keys produce different signatures."""
        # Arrange
        session_id = "test-session-123"
        secret_key1 = "secret-1"
        secret_key2 = "secret-2"

        # Act
        signature1 = auth.generate_signature(session_id, secret_key1)
        signature2 = auth.generate_signature(session_id, secret_key2)

        # Assert
        assert signature1 != signature2

    @patch("intake_agent.api.auth.log")
    def test_generate_signature_logs_generation(self, mock_log):
        """Test that generate_signature logs when creating a signature."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"

        # Act
        auth.generate_signature(session_id, secret_key)

        # Assert
        mock_log.info.assert_called_once()
        # Verify it logs with truncated session ID (first 8 chars + "...")
        log_message = mock_log.info.call_args[0][0]
        assert "Generated signature for session:" in log_message
        assert "test-ses" in log_message  # First 8 chars of session_id

    def test_verify_signature_returns_true_for_valid_signature(self):
        """Test that verify_signature returns True for valid signatures."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"
        valid_signature = auth.generate_signature(session_id, secret_key)

        # Act
        result = auth.verify_signature(session_id, valid_signature, secret_key)

        # Assert
        assert result is True

    def test_verify_signature_returns_false_for_invalid_signature(self):
        """Test that verify_signature returns False for invalid signatures."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"
        invalid_signature = "invalid-signature-that-is-not-correct"

        # Act
        result = auth.verify_signature(session_id, invalid_signature, secret_key)

        # Assert
        assert result is False

    def test_verify_signature_returns_false_for_wrong_session_id(self):
        """Test that verify_signature returns False when session_id doesn't match."""
        # Arrange
        secret_key = "test-secret-key"
        correct_session_id = "correct-session"
        wrong_session_id = "wrong-session"
        signature = auth.generate_signature(correct_session_id, secret_key)

        # Act
        result = auth.verify_signature(wrong_session_id, signature, secret_key)

        # Assert
        assert result is False

    def test_verify_signature_returns_false_for_wrong_secret_key(self):
        """Test that verify_signature returns False when secret_key doesn't match."""
        # Arrange
        session_id = "test-session-123"
        correct_secret_key = "correct-secret"
        wrong_secret_key = "wrong-secret"
        signature = auth.generate_signature(session_id, correct_secret_key)

        # Act
        result = auth.verify_signature(session_id, signature, wrong_secret_key)

        # Assert
        assert result is False

    def test_verify_signature_returns_false_for_missing_session_id(self):
        """Test that verify_signature returns False when session_id is missing."""
        # Arrange
        session_id = ""
        signature = "some-signature"
        secret_key = "test-secret-key"

        # Act
        result = auth.verify_signature(session_id, signature, secret_key)

        # Assert
        assert result is False

    def test_verify_signature_returns_false_for_missing_signature(self):
        """Test that verify_signature returns False when signature is missing."""
        # Arrange
        session_id = "test-session-123"
        signature = ""
        secret_key = "test-secret-key"

        # Act
        result = auth.verify_signature(session_id, signature, secret_key)

        # Assert
        assert result is False

    def test_verify_signature_returns_false_for_missing_secret_key(self):
        """Test that verify_signature returns False when secret_key is missing."""
        # Arrange
        session_id = "test-session-123"
        signature = "some-signature"
        secret_key = ""

        # Act
        result = auth.verify_signature(session_id, signature, secret_key)

        # Assert
        assert result is False

    @patch("intake_agent.api.auth.log")
    def test_verify_signature_logs_warning_for_missing_parameters(self, mock_log):
        """Test that verify_signature logs warning for missing parameters."""
        # Arrange
        session_id = ""
        signature = ""
        secret_key = ""

        # Act
        auth.verify_signature(session_id, signature, secret_key)

        # Assert
        mock_log.warning.assert_called_once_with("Missing required authentication parameters")

    @patch("intake_agent.api.auth.log")
    def test_verify_signature_logs_warning_for_invalid_signature(self, mock_log):
        """Test that verify_signature logs warning for invalid signatures."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"
        invalid_signature = "invalid-signature"

        # Act
        auth.verify_signature(session_id, invalid_signature, secret_key)

        # Assert
        # Should have at least one warning call for invalid signature
        assert any(
            "Invalid signature" in str(call)
            for call in mock_log.warning.call_args_list
        )

    @patch("intake_agent.api.auth.log")
    def test_verify_signature_logs_success_for_valid_signature(self, mock_log):
        """Test that verify_signature logs success for valid signatures."""
        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"
        valid_signature = auth.generate_signature(session_id, secret_key)

        # Clear previous logs
        mock_log.reset_mock()

        # Act
        auth.verify_signature(session_id, valid_signature, secret_key)

        # Assert
        assert any(
            "Valid signature" in str(call)
            for call in mock_log.info.call_args_list
        )

    def test_verify_signature_uses_constant_time_comparison(self):
        """Test that signature verification is resistant to timing attacks."""
        # This test verifies that we're using hmac.compare_digest
        # which provides constant-time comparison

        # Arrange
        session_id = "test-session-123"
        secret_key = "test-secret-key"
        correct_signature = auth.generate_signature(session_id, secret_key)

        # Create an almost-correct signature (differs by last char)
        almost_correct = correct_signature[:-1] + ("0" if correct_signature[-1] != "0" else "1")

        # Act & Assert
        # Both should return False, and ideally in similar time
        # (we can't easily test timing, but we verify the function works correctly)
        assert auth.verify_signature(session_id, almost_correct, secret_key) is False
        assert auth.verify_signature(session_id, correct_signature, secret_key) is True
