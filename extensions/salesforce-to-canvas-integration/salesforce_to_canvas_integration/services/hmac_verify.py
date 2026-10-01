"""HMAC-SHA256 verification of inbound Salesforce Flow webhook requests."""

import hashlib
import hmac

SIGNATURE_HEADER = "X-Signature"
SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Compute the canonical ``sha256=<hex>`` signature for *body*."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, provided_signature: str | None) -> bool:
    """Constant-time verification of an inbound signature.

    Fails closed: a missing secret or a missing/blank signature always returns
    ``False``. Accepts either ``sha256=<hex>`` or a bare hex digest, because
    Salesforce Flow's HTTP Callout custom-header builder occasionally strips
    the scheme prefix.
    """
    if not secret:
        return False
    if not provided_signature:
        return False

    provided = provided_signature.strip()
    expected = compute_signature(secret, body)

    # tolerate bare-hex signatures (no "sha256=" prefix)
    if not provided.startswith(SIGNATURE_PREFIX):
        provided = f"{SIGNATURE_PREFIX}{provided}"

    return hmac.compare_digest(provided, expected)


__all__ = ("SIGNATURE_HEADER", "compute_signature", "verify_signature")
