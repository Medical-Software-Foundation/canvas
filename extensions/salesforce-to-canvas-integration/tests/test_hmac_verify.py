"""Tests for the HMAC signature verifier."""

from __future__ import annotations

import pytest

from salesforce_to_canvas_integration.services.hmac_verify import (
    compute_signature,
    verify_signature,
)


SECRET = "topsecret"
BODY = b'{"Id":"003xx0000000001AAA","FirstName":"Jane"}'


def test_round_trip_accepts_correct_signature() -> None:
    signature = compute_signature(SECRET, BODY)
    assert verify_signature(SECRET, BODY, signature) is True


def test_accepts_bare_hex_without_scheme_prefix() -> None:
    signature = compute_signature(SECRET, BODY).removeprefix("sha256=")
    assert verify_signature(SECRET, BODY, signature) is True


@pytest.mark.parametrize(
    "provided",
    [
        None,
        "",
        "sha256=deadbeef",
        "sha256=" + "f" * 64,
    ],
)
def test_rejects_bad_or_missing_signature(provided: str | None) -> None:
    assert verify_signature(SECRET, BODY, provided) is False


def test_rejects_when_body_tampered() -> None:
    signature = compute_signature(SECRET, BODY)
    assert verify_signature(SECRET, BODY + b"x", signature) is False


def test_fails_closed_on_missing_secret() -> None:
    signature = compute_signature(SECRET, BODY)
    assert verify_signature("", BODY, signature) is False
    assert verify_signature("   ", BODY, signature) is False
