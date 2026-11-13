"""Tests for HMAC-SHA256 webhook signature verification."""

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

from doc_intake_ai.webhook_auth import verify_hmac, MAX_TIMESTAMP_AGE


SECRET = "test-webhook-secret"
BODY = b'{"type": "processor_run.completed", "data": {}}'


def _make_signature(body: bytes, timestamp: str, secret: str) -> str:
    body_str = body.decode("utf-8")
    message = f"v0:{timestamp}:{body_str}"
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class TestVerifyHmac:
    """Test HMAC signature verification."""

    def test_valid_signature(self) -> None:
        ts = str(int(time.time()))
        sig = _make_signature(BODY, ts, SECRET)
        assert verify_hmac(BODY, ts, sig, SECRET) is True

    def test_wrong_signature(self) -> None:
        ts = str(int(time.time()))
        assert verify_hmac(BODY, ts, "bad-signature", SECRET) is False

    def test_wrong_secret(self) -> None:
        ts = str(int(time.time()))
        sig = _make_signature(BODY, ts, SECRET)
        assert verify_hmac(BODY, ts, sig, "wrong-secret") is False

    def test_stale_timestamp(self) -> None:
        ts = str(int(time.time()) - MAX_TIMESTAMP_AGE - 60)
        sig = _make_signature(BODY, ts, SECRET)
        assert verify_hmac(BODY, ts, sig, SECRET) is False

    def test_future_timestamp_within_window(self) -> None:
        ts = str(int(time.time()) + 60)
        sig = _make_signature(BODY, ts, SECRET)
        assert verify_hmac(BODY, ts, sig, SECRET) is True

    def test_future_timestamp_outside_window(self) -> None:
        ts = str(int(time.time()) + MAX_TIMESTAMP_AGE + 60)
        sig = _make_signature(BODY, ts, SECRET)
        assert verify_hmac(BODY, ts, sig, SECRET) is False

    def test_missing_body(self) -> None:
        ts = str(int(time.time()))
        assert verify_hmac(b"", ts, "sig", SECRET) is False

    def test_missing_timestamp(self) -> None:
        assert verify_hmac(BODY, "", "sig", SECRET) is False

    def test_missing_signature(self) -> None:
        ts = str(int(time.time()))
        assert verify_hmac(BODY, ts, "", SECRET) is False

    def test_missing_secret(self) -> None:
        ts = str(int(time.time()))
        assert verify_hmac(BODY, ts, "sig", "") is False

    def test_non_numeric_timestamp(self) -> None:
        assert verify_hmac(BODY, "not-a-number", "sig", SECRET) is False

    def test_tampered_body(self) -> None:
        ts = str(int(time.time()))
        sig = _make_signature(BODY, ts, SECRET)
        tampered = b'{"type": "processor_run.completed", "data": {"evil": true}}'
        assert verify_hmac(tampered, ts, sig, SECRET) is False
