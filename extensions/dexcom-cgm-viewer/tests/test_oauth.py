"""``oauth`` orchestration: load, persist, refresh-on-401."""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock

import pytest

from dexcom_cgm_viewer.lib import oauth, storage
from dexcom_cgm_viewer.lib.crypto import TokenCipher
from dexcom_cgm_viewer.lib.dexcom_client import DexcomAuthError, TokenSet
from dexcom_cgm_viewer.models import DexcomOAuthToken


PATIENT = "patient-oauth-1"


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def cipher() -> TokenCipher:
    return TokenCipher()


def _seed_tokens(cipher: TokenCipher) -> None:
    storage.upsert_tokens(
        PATIENT,
        access_token_ciphertext=cipher.encrypt("AT-OLD"),
        refresh_token_ciphertext=cipher.encrypt("RT-OLD"),
        expires_at=_now(),
        dexcom_user_id="DEX",
        now=_now(),
        is_initial_connection=True,
    )


def test_load_tokens_decrypts_stored_row(cipher: TokenCipher) -> None:
    _seed_tokens(cipher)
    loaded = oauth.load_tokens(PATIENT, cipher)
    assert loaded.access_token == "AT-OLD"
    assert loaded.refresh_token == "RT-OLD"
    assert loaded.dexcom_user_id == "DEX"


def test_load_tokens_raises_when_missing(cipher: TokenCipher) -> None:
    with pytest.raises(oauth.TokensNotFound):
        oauth.load_tokens("nobody", cipher)


def test_persist_tokens_stores_and_marks_initial(cipher: TokenCipher) -> None:
    new = TokenSet(
        access_token="AT-NEW", refresh_token="RT-NEW",
        expires_in=7200, token_type="Bearer", dexcom_user_id="USR",
    )
    oauth.persist_tokens(
        PATIENT, cipher, new, is_initial_connection=True, now=_now(),
    )
    stored = DexcomOAuthToken.objects.get(patient_id=PATIENT)
    assert cipher.decrypt(stored.access_token) == "AT-NEW"
    assert cipher.decrypt(stored.refresh_token) == "RT-NEW"
    assert stored.connected_at == _now()


def test_refresh_and_persist_rotates_stored_tokens(cipher: TokenCipher) -> None:
    _seed_tokens(cipher)
    client = MagicMock()
    client.refresh.return_value = TokenSet(
        access_token="AT2", refresh_token="RT2", expires_in=7200,
        token_type="Bearer", dexcom_user_id="DEX",
    )
    rotated = oauth.refresh_and_persist(
        PATIENT, client, cipher, "RT-OLD", now=_now(),
    )
    assert rotated.access_token == "AT2"
    assert rotated.refresh_token == "RT2"
    stored = DexcomOAuthToken.objects.get(patient_id=PATIENT)
    assert cipher.decrypt(stored.access_token) == "AT2"
    assert cipher.decrypt(stored.refresh_token) == "RT2"


def test_refresh_and_persist_wraps_auth_error_as_refresh_failed(cipher: TokenCipher) -> None:
    client = MagicMock()
    client.refresh.side_effect = DexcomAuthError("rejected")
    with pytest.raises(oauth.RefreshFailed):
        oauth.refresh_and_persist(
            PATIENT, client, cipher, "any-refresh-token", now=_now(),
        )
