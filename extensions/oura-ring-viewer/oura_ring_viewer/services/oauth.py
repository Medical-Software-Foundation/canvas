"""OAuth orchestration: refresh-on-401 with single-use token rotation.

The pattern is:

    tokens = load_tokens(patient_id, cipher)
    try:
        result = call_oura_with(tokens.access_token)
    except OuraAuthError:
        tokens = refresh_and_persist(patient_id, client, cipher, tokens.refresh_token, now=now)
        result = call_oura_with(tokens.access_token)

Oura refresh tokens are single use. The new refresh token must be stored every
time one is issued, or the next refresh is locked out and the patient has to
reconnect.
"""

import datetime as dt
from dataclasses import dataclass

from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.oura_client import (
    OuraAPIError,
    OuraAuthError,
    OuraClient,
    TokenSet,
)
from oura_ring_viewer.services.storage import get_tokens, upsert_tokens


class TokensNotFound(RuntimeError):
    """The patient has no stored tokens: they never connected, or disconnected."""


class RefreshFailed(RuntimeError):
    """The refresh request failed. The patient needs to reconnect."""


@dataclass
class LoadedTokens:
    """Decrypted token bundle ready to drive Oura calls."""

    access_token: str
    refresh_token: str
    expires_at: dt.datetime


def load_tokens(patient_id: str, cipher: TokenCipher) -> LoadedTokens:
    """Load and decrypt the stored token row. Raises TokensNotFound if absent."""
    row = get_tokens(patient_id)
    if row is None:
        raise TokensNotFound(patient_id)
    return LoadedTokens(
        access_token=cipher.decrypt(row.access_token),
        refresh_token=cipher.decrypt(row.refresh_token),
        expires_at=row.expires_at,
    )


def persist_tokens(
    patient_id: str,
    cipher: TokenCipher,
    tokens: TokenSet,
    *,
    is_initial_connection: bool,
    now: dt.datetime,
) -> None:
    """Encrypt and store fresh tokens. Always rotates the refresh token."""
    upsert_tokens(
        patient_id,
        access_token_ciphertext=cipher.encrypt(tokens.access_token),
        refresh_token_ciphertext=cipher.encrypt(tokens.refresh_token),
        expires_at=tokens.expires_at,
        scopes=tokens.scope,
        now=now,
        is_initial_connection=is_initial_connection,
    )


def refresh_and_persist(
    patient_id: str,
    client: OuraClient,
    cipher: TokenCipher,
    refresh_token: str,
    *,
    now: dt.datetime,
) -> LoadedTokens:
    """Refresh access via Oura and store the rotated refresh token."""
    try:
        new_tokens = client.refresh(refresh_token)
    except (OuraAuthError, OuraAPIError) as exc:
        raise RefreshFailed(str(exc)) from exc
    persist_tokens(patient_id, cipher, new_tokens, is_initial_connection=False, now=now)
    return LoadedTokens(
        access_token=new_tokens.access_token,
        refresh_token=new_tokens.refresh_token,
        expires_at=new_tokens.expires_at,
    )
