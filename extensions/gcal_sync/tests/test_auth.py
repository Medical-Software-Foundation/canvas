"""Tests for the service-account assertion construction and fail-closed config parsing."""

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from gcal_sync.google.auth import (
    CALENDAR_SCOPE,
    DEFAULT_TOKEN_URI,
    GoogleAuthError,
    build_assertion,
    parse_service_account,
)


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def test_parse_rejects_missing_secret():
    with pytest.raises(GoogleAuthError):
        parse_service_account(None)
    with pytest.raises(GoogleAuthError):
        parse_service_account("   ")


def test_parse_rejects_invalid_json():
    with pytest.raises(GoogleAuthError):
        parse_service_account("{not json")


def test_parse_rejects_missing_required_fields():
    with pytest.raises(GoogleAuthError):
        parse_service_account('{"client_email": "svc@x.iam"}')  # no private_key


def test_parse_accepts_valid_service_account():
    sa = parse_service_account('{"client_email": "svc@x.iam", "private_key": "KEY"}')
    assert sa["client_email"] == "svc@x.iam"


def test_assertion_has_expected_claims(keypair):
    private_pem, public_pem = keypair
    service_account = {
        "client_email": "svc@project.iam.gserviceaccount.com",
        "private_key": private_pem,
    }
    token = build_assertion(service_account, subject="dr.who@example.com", issued_at=1_000_000)

    # The token must be verifiable with the service account's public key (proves RS256 signing).
    claims = jwt.decode(
        token,
        public_pem,
        algorithms=["RS256"],
        audience=DEFAULT_TOKEN_URI,
        # issued_at is a fixed past value for determinism, so don't enforce expiry here.
        options={"verify_exp": False},
    )
    assert claims["iss"] == "svc@project.iam.gserviceaccount.com"
    # Impersonation: the subject is the provider, enabling domain-wide delegation.
    assert claims["sub"] == "dr.who@example.com"
    assert claims["scope"] == CALENDAR_SCOPE
    assert claims["aud"] == DEFAULT_TOKEN_URI
    assert claims["iat"] == 1_000_000
    assert claims["exp"] == 1_000_000 + 3600


def test_assertion_uses_custom_token_uri(keypair):
    private_pem, _ = keypair
    service_account = {
        "client_email": "svc@x.iam",
        "private_key": private_pem,
        "token_uri": "https://oauth2.example.test/token",
    }
    token = build_assertion(service_account, subject="x@example.com", issued_at=42)
    claims = jwt.decode(
        token, options={"verify_signature": False}, algorithms=["RS256"]
    )
    assert claims["aud"] == "https://oauth2.example.test/token"
