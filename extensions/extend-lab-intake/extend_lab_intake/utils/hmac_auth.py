"""HMAC signature authentication utilities.

Provides session token generation and verification for secure API authentication
without exposing raw API tokens to the frontend.

The flow:
1. Server generates a time-limited session token when rendering the page
2. Browser includes this token in requests via Authorization header
3. Server validates the token signature and expiry
"""

from __future__ import annotations

import hashlib
import hmac
import time


# Session token validity (5 minutes)
SESSION_TOKEN_EXPIRY_SECONDS = 300


def generate_session_token(secret_key: str, timestamp: int | None = None) -> str:
    """Generate a time-limited session token for frontend use.

    The token format is: {timestamp}.{signature}
    where signature = HMAC-SHA256(secret_key, "session:{timestamp}")

    Args:
        secret_key: The API secret key
        timestamp: Unix timestamp (defaults to current time)

    Returns:
        Session token string in format "timestamp.signature"
    """
    if timestamp is None:
        timestamp = int(time.time())

    timestamp_str = str(timestamp)

    # Generate signature over the session identifier
    message = f"session:{timestamp_str}"
    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{timestamp_str}.{signature}"


def verify_session_token(
    secret_key: str,
    token: str,
    max_age_seconds: int = SESSION_TOKEN_EXPIRY_SECONDS,
) -> tuple[bool, str]:
    """Verify a session token from a request.

    Args:
        secret_key: The API secret key
        token: Session token from request (format: "timestamp.signature")
        max_age_seconds: Maximum age of token in seconds

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not secret_key:
        return False, "Secret key not configured"

    if not token:
        return False, "Missing token"

    # Parse token
    parts = token.split(".", 1)
    if len(parts) != 2:
        return False, "Invalid token format"

    timestamp_str, provided_signature = parts

    # Validate timestamp
    try:
        token_time = int(timestamp_str)
    except ValueError:
        return False, "Invalid timestamp in token"

    current_time = int(time.time())

    # Check if token has expired (only check if it's too old, not future)
    if current_time - token_time > max_age_seconds:
        return False, "Token expired"

    # Check for future timestamps (clock skew allowance of 60 seconds)
    if token_time - current_time > 60:
        return False, "Token timestamp in future"

    # Recreate the expected signature
    message = f"session:{timestamp_str}"
    expected_signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(provided_signature, expected_signature):
        return False, "Invalid signature"

    return True, ""
