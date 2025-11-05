"""
Authentication module for intake agent.

Uses HMAC-SHA256 to sign session IDs with the PLUGIN_SECRET_KEY.
Clients must provide the signature with each request for verification.
"""

import hashlib
import hmac

from logger import log


def generate_signature(session_id: str, secret_key: str) -> str:
    """
    Generate HMAC-SHA256 signature for a session ID.

    Args:
        session_id: The session identifier to sign
        secret_key: The secret key for signing

    Returns:
        Hexadecimal signature string
    """
    signature = hmac.new(
        secret_key.encode('utf-8'),
        session_id.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    log.info(f"Generated signature for session: {session_id[:8]}...")
    return signature


def verify_signature(session_id: str, provided_signature: str, secret_key: str) -> bool:
    """
    Verify that a provided signature matches the expected signature for a session.

    Args:
        session_id: The session identifier
        provided_signature: The signature provided by the client
        secret_key: The secret key for verification

    Returns:
        True if signature is valid, False otherwise
    """
    if not session_id or not provided_signature or not secret_key:
        log.warning("Missing required authentication parameters")
        return False

    expected_signature = generate_signature(session_id, secret_key)

    # Use constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(expected_signature, provided_signature)

    if not is_valid:
        log.warning(f"Invalid signature for session: {session_id[:8]}...")
    else:
        log.info(f"Valid signature for session: {session_id[:8]}...")

    return is_valid
