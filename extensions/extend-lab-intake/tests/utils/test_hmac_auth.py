"""Tests for HMAC authentication utilities."""

import time

import pytest

from extend_lab_intake.utils.hmac_auth import (
    SESSION_TOKEN_EXPIRY_SECONDS,
    generate_session_token,
    verify_session_token,
)


class TestGenerateSessionToken:
    """Tests for generate_session_token function."""

    def test_generates_token_with_current_timestamp(self) -> None:
        """Test that token is generated with current timestamp."""
        current_time = int(time.time())
        token = generate_session_token("secret_key")

        # Token format: timestamp.signature
        parts = token.split(".")
        assert len(parts) == 2

        timestamp = int(parts[0])
        # Allow 1 second tolerance
        assert abs(timestamp - current_time) <= 1

    def test_generates_token_with_custom_timestamp(self) -> None:
        """Test that custom timestamp is used."""
        custom_time = 1700000000
        token = generate_session_token("secret_key", timestamp=custom_time)

        parts = token.split(".")
        assert parts[0] == str(custom_time)

    def test_signature_is_consistent(self) -> None:
        """Test that same inputs produce same signature."""
        timestamp = 1700000000
        token1 = generate_session_token("secret_key", timestamp=timestamp)
        token2 = generate_session_token("secret_key", timestamp=timestamp)

        assert token1 == token2

    def test_different_keys_produce_different_signatures(self) -> None:
        """Test that different keys produce different signatures."""
        timestamp = 1700000000
        token1 = generate_session_token("secret_key_1", timestamp=timestamp)
        token2 = generate_session_token("secret_key_2", timestamp=timestamp)

        assert token1 != token2

    def test_different_timestamps_produce_different_signatures(self) -> None:
        """Test that different timestamps produce different signatures."""
        token1 = generate_session_token("secret_key", timestamp=1700000000)
        token2 = generate_session_token("secret_key", timestamp=1700000001)

        assert token1 != token2

    def test_signature_format_is_hex(self) -> None:
        """Test that signature is hexadecimal."""
        token = generate_session_token("secret_key", timestamp=1700000000)
        signature = token.split(".")[1]

        # Should be 64 hex characters (256 bits / 4 bits per hex char)
        assert len(signature) == 64
        assert all(c in "0123456789abcdef" for c in signature)


class TestVerifySessionToken:
    """Tests for verify_session_token function."""

    def test_valid_token_passes(self) -> None:
        """Test that a valid token is accepted."""
        token = generate_session_token("secret_key")
        is_valid, error = verify_session_token("secret_key", token)

        assert is_valid is True
        assert error == ""

    def test_expired_token_fails(self) -> None:
        """Test that an expired token is rejected."""
        # Generate token with old timestamp
        old_time = int(time.time()) - SESSION_TOKEN_EXPIRY_SECONDS - 10
        token = generate_session_token("secret_key", timestamp=old_time)

        is_valid, error = verify_session_token("secret_key", token)

        assert is_valid is False
        assert "expired" in error.lower()

    def test_future_token_fails(self) -> None:
        """Test that a token with future timestamp is rejected."""
        # Generate token with future timestamp (beyond clock skew allowance)
        future_time = int(time.time()) + 120
        token = generate_session_token("secret_key", timestamp=future_time)

        is_valid, error = verify_session_token("secret_key", token)

        assert is_valid is False
        assert "future" in error.lower()

    def test_future_token_within_skew_passes(self) -> None:
        """Test that token within clock skew allowance passes."""
        # Generate token slightly in the future (within 60 second allowance)
        future_time = int(time.time()) + 30
        token = generate_session_token("secret_key", timestamp=future_time)

        is_valid, error = verify_session_token("secret_key", token)

        assert is_valid is True
        assert error == ""

    def test_wrong_key_fails(self) -> None:
        """Test that wrong key is rejected."""
        token = generate_session_token("secret_key")
        is_valid, error = verify_session_token("wrong_key", token)

        assert is_valid is False
        assert "invalid" in error.lower()

    def test_tampered_signature_fails(self) -> None:
        """Test that tampered signature is rejected."""
        token = generate_session_token("secret_key")
        parts = token.split(".")
        tampered_token = f"{parts[0]}.{'0' * 64}"

        is_valid, error = verify_session_token("secret_key", tampered_token)

        assert is_valid is False
        assert "invalid" in error.lower()

    def test_tampered_timestamp_fails(self) -> None:
        """Test that tampered timestamp is rejected."""
        token = generate_session_token("secret_key")
        parts = token.split(".")
        # Change timestamp but keep original signature
        tampered_token = f"{int(parts[0]) + 1}.{parts[1]}"

        is_valid, error = verify_session_token("secret_key", tampered_token)

        assert is_valid is False
        assert "invalid" in error.lower()

    def test_missing_secret_key_fails(self) -> None:
        """Test that empty secret key is rejected."""
        token = generate_session_token("secret_key")
        is_valid, error = verify_session_token("", token)

        assert is_valid is False
        assert "not configured" in error.lower()

    def test_missing_token_fails(self) -> None:
        """Test that empty token is rejected."""
        is_valid, error = verify_session_token("secret_key", "")

        assert is_valid is False
        assert "missing" in error.lower()

    def test_invalid_token_format_fails(self) -> None:
        """Test that malformed token is rejected."""
        is_valid, error = verify_session_token("secret_key", "not-a-valid-token")

        assert is_valid is False
        assert "invalid" in error.lower()

    def test_invalid_timestamp_format_fails(self) -> None:
        """Test that non-numeric timestamp is rejected."""
        is_valid, error = verify_session_token("secret_key", "abc.signature")

        assert is_valid is False
        assert "invalid" in error.lower()

    def test_custom_max_age(self) -> None:
        """Test custom max_age_seconds parameter."""
        # Generate token 100 seconds ago
        old_time = int(time.time()) - 100
        token = generate_session_token("secret_key", timestamp=old_time)

        # Should pass with default 300 second expiry
        is_valid, _ = verify_session_token("secret_key", token, max_age_seconds=300)
        assert is_valid is True

        # Should fail with 60 second expiry
        is_valid, error = verify_session_token("secret_key", token, max_age_seconds=60)
        assert is_valid is False
        assert "expired" in error.lower()

    def test_token_just_before_expiry(self) -> None:
        """Test token at boundary of expiry window."""
        # Generate token just under the expiry limit
        old_time = int(time.time()) - (SESSION_TOKEN_EXPIRY_SECONDS - 1)
        token = generate_session_token("secret_key", timestamp=old_time)

        is_valid, error = verify_session_token("secret_key", token)

        assert is_valid is True
        assert error == ""

    def test_token_just_after_expiry(self) -> None:
        """Test token just past expiry window."""
        # Generate token just over the expiry limit
        old_time = int(time.time()) - (SESSION_TOKEN_EXPIRY_SECONDS + 1)
        token = generate_session_token("secret_key", timestamp=old_time)

        is_valid, error = verify_session_token("secret_key", token)

        assert is_valid is False
        assert "expired" in error.lower()
