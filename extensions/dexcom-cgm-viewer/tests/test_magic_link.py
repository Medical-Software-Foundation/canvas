"""Magic-link JWT and OAuth state signing."""

from __future__ import annotations

import jwt
import pytest

from dexcom_cgm_viewer.lib import magic_link
from dexcom_cgm_viewer.lib.settings import MAGIC_LINK_TTL_SECONDS


SECRET = "x" * 64


def test_mint_then_verify_roundtrip() -> None:
    token, nonce = magic_link.mint("patient-1", SECRET, now=1_000_000)
    claims = magic_link.verify(token, SECRET, now=1_000_001)
    assert claims.patient_id == "patient-1"
    assert claims.nonce == nonce
    assert claims.issued_at == 1_000_000
    assert claims.expires_at == 1_000_000 + MAGIC_LINK_TTL_SECONDS


def test_mint_validates_inputs() -> None:
    with pytest.raises(ValueError):
        magic_link.mint("", SECRET, now=0)
    with pytest.raises(ValueError):
        magic_link.mint("patient-1", "", now=0)


def test_verify_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="malformed"):
        magic_link.verify("", SECRET)


def test_verify_rejects_missing_secret() -> None:
    token, _ = magic_link.mint("p", SECRET, now=0)
    with pytest.raises(ValueError, match="secret is required"):
        magic_link.verify(token, "")


def test_verify_detects_signature_mismatch() -> None:
    token, _ = magic_link.mint("p", SECRET, now=0)
    with pytest.raises(ValueError, match="rejected"):
        magic_link.verify(token, "wrong-secret-of-the-correct-length-padding")


def test_verify_rejects_expired_token() -> None:
    token, _ = magic_link.mint("p", SECRET, now=0)
    with pytest.raises(ValueError, match="expired"):
        magic_link.verify(token, SECRET, now=MAGIC_LINK_TTL_SECONDS + 1)


def test_verify_rejects_token_exp_via_pyjwt_when_now_omitted() -> None:
    # When the caller doesn't pin time, PyJWT itself enforces ``exp``.
    token, _ = magic_link.mint("p", SECRET, now=0)
    with pytest.raises(ValueError, match="expired"):
        magic_link.verify(token, SECRET)


def test_verify_rejects_payload_with_missing_claims() -> None:
    # Sign a JWT with the correct secret but missing required custom claims.
    forged = jwt.encode({"p": "", "iat": 0, "exp": 9_999_999_999}, SECRET, algorithm="HS256")
    with pytest.raises(ValueError, match="missing required claims"):
        magic_link.verify(forged, SECRET, now=0)


def test_state_sign_verify_roundtrip() -> None:
    state = magic_link.sign_state("patient-2", "abc-nonce", SECRET)
    pid, nonce = magic_link.verify_state(state, SECRET)
    assert pid == "patient-2"
    assert nonce == "abc-nonce"


def test_state_sign_validates_inputs() -> None:
    with pytest.raises(ValueError):
        magic_link.sign_state("", "n", SECRET)
    with pytest.raises(ValueError):
        magic_link.sign_state("p", "", SECRET)


def test_state_verify_rejects_empty_or_tampered() -> None:
    with pytest.raises(ValueError, match="malformed"):
        magic_link.verify_state("", SECRET)
    state = magic_link.sign_state("p", "n", SECRET)
    with pytest.raises(ValueError, match="rejected"):
        magic_link.verify_state(state, "different-secret-of-the-same-padding-length")


def test_state_verify_rejects_missing_claims() -> None:
    forged = jwt.encode({"p": ""}, SECRET, algorithm="HS256")
    with pytest.raises(ValueError, match="missing required claims"):
        magic_link.verify_state(forged, SECRET)
