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

Two requests can try to refresh with the same token, for instance two staff
members on one chart. Oura accepts one and rejects the other. The rejected
request must not mark the patient as needing to reconnect, so it first checks
whether the stored token has changed and, if so, uses the winner's tokens.
"""

import datetime as dt
import time
from dataclasses import dataclass

from logger import log

from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.oura_client import (
    OuraAPIError,
    OuraAuthError,
    OuraClient,
    TokenSet,
)
from oura_ring_viewer.services.settings import REFRESH_RACE_WAIT_SECONDS
from oura_ring_viewer.services.storage import get_tokens, upsert_tokens


class TokensNotFound(RuntimeError):
    """The patient has no stored tokens: they never connected, or disconnected."""


class RefreshFailed(RuntimeError):
    """Oura refused the refresh token. The patient needs to reconnect."""


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


def _rotated_elsewhere(
    patient_id: str, cipher: TokenCipher, used_refresh_token: str
) -> LoadedTokens | None:
    """The stored tokens, if another request has replaced the one just refused."""
    try:
        stored = load_tokens(patient_id, cipher)
    except TokensNotFound:
        return None
    return stored if stored.refresh_token != used_refresh_token else None


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
    """Refresh access via Oura and store the rotated refresh token.

    A refusal raises ``RefreshFailed`` unless another request already rotated
    the token. ``OuraAPIError`` passes through untouched: Oura being down says
    nothing about the token, so it must not cost the patient their connection.
    """
    try:
        new_tokens = client.refresh(refresh_token)
    except OuraAuthError as exc:
        current = _rotated_elsewhere(patient_id, cipher, refresh_token)
        if current is None:
            time.sleep(REFRESH_RACE_WAIT_SECONDS)
            current = _rotated_elsewhere(patient_id, cipher, refresh_token)
        if current is None:
            raise RefreshFailed(str(exc)) from exc
        return current
    persist_tokens(patient_id, cipher, new_tokens, is_initial_connection=False, now=now)
    return LoadedTokens(
        access_token=new_tokens.access_token,
        refresh_token=new_tokens.refresh_token,
        expires_at=new_tokens.expires_at,
    )


def revoke_at_oura(
    patient_id: str, client: OuraClient, cipher: TokenCipher, *, now: dt.datetime
) -> bool:
    """End the app's access at Oura. Returns whether Oura confirmed it.

    Best effort: the caller removes the local connection whatever happens
    here, because a patient's decision to stop sharing cannot wait on Oura. An
    expired access token is refreshed once, since Oura only revokes by access
    token.
    """
    try:
        tokens = load_tokens(patient_id, cipher)
        try:
            client.revoke(tokens.access_token)
        except OuraAuthError:
            tokens = refresh_and_persist(patient_id, client, cipher, tokens.refresh_token, now=now)
            client.revoke(tokens.access_token)
    except TokensNotFound:
        return True  # Never connected, or a link still pending: nothing at Oura.
    except (RefreshFailed, OuraAuthError, OuraAPIError) as exc:
        log.warning(f"oura revoke for {patient_id} not confirmed: {type(exc).__name__}")
        return False
    return True
