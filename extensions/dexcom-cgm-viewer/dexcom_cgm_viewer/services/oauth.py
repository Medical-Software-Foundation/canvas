"""OAuth orchestration: token refresh-on-401 with single-use rotation.

The pattern is:

    tokens = load_tokens(patient_id, secrets)
    try:
        result = call_dexcom_with(tokens.access_token)
    except DexcomAuthError:
        tokens = refresh_and_persist(patient_id, secrets, tokens.refresh_token)
        result = call_dexcom_with(tokens.access_token)

The plugin must rotate the refresh token atomically every time Dexcom
returns a new one, or the next refresh will be locked out.
"""

import datetime as dt
from dataclasses import dataclass

from dexcom_cgm_viewer.services.crypto import TokenCipher
from dexcom_cgm_viewer.services.storage import get_tokens, upsert_tokens
from dexcom_cgm_viewer.services.dexcom_client import (
    DexcomAuthError,
    DexcomClient,
    TokenSet,
)


class TokensNotFound(RuntimeError):
    """Raised when the patient has no stored tokens (i.e. never connected)."""


class RefreshFailed(RuntimeError):
    """Raised when the refresh request fails — caller should mark sync error."""


@dataclass
class LoadedTokens:
    """Decrypted token bundle ready to drive Dexcom calls."""

    access_token: str
    refresh_token: str
    expires_at: dt.datetime
    dexcom_user_id: str


def load_tokens(patient_id: str, cipher: TokenCipher) -> LoadedTokens:
    """Load and decrypt the stored token row. Raises ``TokensNotFound`` if missing."""
    row = get_tokens(patient_id)
    if row is None:
        raise TokensNotFound(patient_id)
    return LoadedTokens(
        access_token=cipher.decrypt(row.access_token),
        refresh_token=cipher.decrypt(row.refresh_token),
        expires_at=row.expires_at,
        dexcom_user_id=row.dexcom_user_id,
    )


def persist_tokens(
    patient_id: str,
    cipher: TokenCipher,
    tokens: TokenSet,
    *,
    is_initial_connection: bool,
    now: dt.datetime,
) -> None:
    """Encrypt and store fresh tokens. Always rotates ``refresh_token``."""
    upsert_tokens(
        patient_id,
        access_token_ciphertext=cipher.encrypt(tokens.access_token),
        refresh_token_ciphertext=cipher.encrypt(tokens.refresh_token),
        expires_at=tokens.expires_at,
        dexcom_user_id=tokens.dexcom_user_id,
        now=now,
        is_initial_connection=is_initial_connection,
    )


def refresh_and_persist(
    patient_id: str,
    client: DexcomClient,
    cipher: TokenCipher,
    refresh_token: str,
    *,
    now: dt.datetime,
) -> LoadedTokens:
    """Refresh access via Dexcom and atomically rotate the stored refresh token."""
    try:
        new_tokens = client.refresh(refresh_token)
    except DexcomAuthError as exc:
        raise RefreshFailed(str(exc)) from exc
    persist_tokens(
        patient_id, cipher, new_tokens, is_initial_connection=False, now=now,
    )
    return LoadedTokens(
        access_token=new_tokens.access_token,
        refresh_token=new_tokens.refresh_token,
        expires_at=new_tokens.expires_at,
        dexcom_user_id=new_tokens.dexcom_user_id,
    )
