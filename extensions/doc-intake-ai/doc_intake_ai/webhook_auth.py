"""HMAC-SHA256 signature verification for Extend AI webhooks."""

import hashlib
import hmac
import time


MAX_TIMESTAMP_AGE = 300


def verify_hmac(
    body: bytes,
    timestamp: str,
    signature: str,
    secret: str,
) -> bool:
    """Verify an Extend AI webhook signature.

    Returns True if the signature is valid and the timestamp is within
    MAX_TIMESTAMP_AGE seconds of the current time.
    """
    if not body or not timestamp or not signature or not secret:
        return False

    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    if abs(time.time() - ts) > MAX_TIMESTAMP_AGE:
        return False

    body_str = body.decode("utf-8") if isinstance(body, bytes) else body
    message = f"v0:{timestamp}:{body_str}"
    expected = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
