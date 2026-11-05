"""Tests for the patient-facing OAuth bridge, against real tables and templates."""

import time
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from canvas_sdk.effects.simple_api import HTMLResponse
from canvas_sdk.handlers.simple_api.security import Credentials

from oura_ring_viewer.models import OuraOAuthToken
from oura_ring_viewer.protocols.oauth_api import OuraOAuthAPI
from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.oura_client import OuraAPIError, OuraAuthError, TokenSet
from oura_ring_viewer.services.storage import get_sync_state, upsert_sync_state

PATIENT = "abc123"
SECRET = "m" * 40
SECRETS = {
    "OURA_CLIENT_ID": "cid",
    "OURA_CLIENT_SECRET": "sec",
    "OURA_REDIRECT_URI": "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/callback",
    "OURA_ENVIRONMENT": "sandbox",
    "OURA_MAGIC_LINK_SECRET": SECRET,
}


class _Request:
    def __init__(self, query: dict[str, str]) -> None:
        self.query_params = query
        self.headers: dict[str, str] = {}


class _Event:
    def __init__(self, path: str) -> None:
        self.context = {"method": "GET", "path": path}


def _api(path: str, query: dict[str, str], secrets: dict[str, str] | None = None) -> OuraOAuthAPI:
    handler = OuraOAuthAPI(event=_Event(path))
    handler.request = _Request(query)
    handler.secrets = SECRETS if secrets is None else secrets
    return handler


def _page(effect: Any) -> str:
    assert isinstance(effect, HTMLResponse)
    return str(effect.content.decode())


def _pending_link(nonce: str = "nonce-1") -> str:
    upsert_sync_state(PATIENT, last_link_nonce=nonce, link_pending=True)
    return magic_link.mint_link(PATIENT, nonce, SECRET, now=int(time.time()))


def _state(nonce: str = "nonce-1") -> str:
    return magic_link.sign_state(PATIENT, nonce, SECRET, now=int(time.time()))


def _client(tokens: Any = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    if error is not None:
        client.exchange_code.side_effect = error
    else:
        client.exchange_code.return_value = tokens or TokenSet("AT", "RT", 86_400, "bearer", "daily spo2")
    return client


def test_authenticate_always_defers_to_the_handler() -> None:
    assert _api("/connect", {}).authenticate(Credentials(MagicMock())) is True


class TestConnect:
    def test_valid_link_redirects_to_oura_with_a_signed_state(self) -> None:
        effect = _api("/connect", {"token": _pending_link()}).connect()[0]
        assert effect.status_code == HTTPStatus.FOUND
        location = urlparse(effect.headers["Location"])
        query = parse_qs(location.query)
        assert f"{location.scheme}://{location.netloc}{location.path}" == (
            "https://cloud.ouraring.com/oauth/authorize"
        )
        assert query["scope"] == ["daily spo2"]
        claims = magic_link.verify_state(query["state"][0], SECRET)
        assert (claims.patient_id, claims.nonce) == (PATIENT, "nonce-1")

    def test_the_link_stays_usable_until_the_callback_completes(self) -> None:
        """A patient who backs out of Oura's consent page can tap the link again."""
        token = _pending_link()
        _api("/connect", {"token": token}).connect()
        assert _api("/connect", {"token": token}).connect()[0].status_code == HTTPStatus.FOUND

    def test_missing_token(self) -> None:
        effect = _api("/connect", {}).connect()[0]
        assert effect.status_code == HTTPStatus.BAD_REQUEST
        assert "incomplete" in _page(effect)

    def test_incomplete_configuration(self) -> None:
        effect = _api("/connect", {"token": "x"}, secrets={}).connect()[0]
        assert effect.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    @pytest.mark.parametrize("token", ["garbage", "a.b.c"])
    def test_invalid_token(self, token: str) -> None:
        effect = _api("/connect", {"token": token}).connect()[0]
        assert effect.status_code == HTTPStatus.UNAUTHORIZED
        assert "expired or is not valid" in _page(effect)

    def test_expired_link(self) -> None:
        upsert_sync_state(PATIENT, last_link_nonce="nonce-1", link_pending=True)
        old = magic_link.mint_link(PATIENT, "nonce-1", SECRET, now=int(time.time()) - 73 * 3600)
        assert _api("/connect", {"token": old}).connect()[0].status_code == HTTPStatus.UNAUTHORIZED

    def test_a_state_token_is_not_a_link(self) -> None:
        _pending_link()
        effect = _api("/connect", {"token": _state()}).connect()[0]
        assert effect.status_code == HTTPStatus.UNAUTHORIZED

    def test_a_superseded_link_no_longer_works(self) -> None:
        old = _pending_link("nonce-old")
        _pending_link("nonce-new")
        effect = _api("/connect", {"token": old}).connect()[0]
        assert effect.status_code == HTTPStatus.CONFLICT
        assert "newer one" in _page(effect)


class TestCallback:
    def test_success_stores_tokens_and_burns_the_nonce(self) -> None:
        _pending_link()
        upsert_sync_state(PATIENT, last_error="refresh_failed")
        with patch("oura_ring_viewer.protocols.oauth_api.build_client", return_value=_client()) as build:
            effect = _api("/callback", {"code": "c0de", "state": _state()}).callback()[0]

        assert effect.status_code == HTTPStatus.OK
        assert "Your Oura Ring is connected" in _page(effect)
        build.return_value.exchange_code.assert_called_once_with("c0de")
        stored = OuraOAuthToken.objects.get(patient_id=PATIENT)
        assert (stored.access_token, stored.refresh_token, stored.scopes) == ("AT", "RT", "daily spo2")
        state = get_sync_state(PATIENT)
        assert state is not None
        assert (state.last_link_nonce, state.link_pending, state.last_error) == ("", False, "")

    def test_a_completed_callback_cannot_be_replayed(self) -> None:
        _pending_link()
        state = _state()
        with patch("oura_ring_viewer.protocols.oauth_api.build_client", return_value=_client()):
            _api("/callback", {"code": "c0de", "state": state}).callback()
            replay = _api("/callback", {"code": "c0de", "state": state}).callback()[0]
        assert replay.status_code == HTTPStatus.CONFLICT

    def test_patient_declined_on_oura(self) -> None:
        _pending_link()
        with patch("oura_ring_viewer.protocols.oauth_api.build_client") as build:
            effect = _api("/callback", {"error": "access_denied", "state": _state()}).callback()[0]
        build.assert_not_called()
        assert effect.status_code == HTTPStatus.OK
        assert "chose not to share" in _page(effect)
        assert not OuraOAuthToken.objects.filter(patient_id=PATIENT).exists()

    @pytest.mark.parametrize("query", [{}, {"code": "c"}, {"state": "s"}])
    def test_missing_parameters(self, query: dict[str, str]) -> None:
        assert _api("/callback", query).callback()[0].status_code == HTTPStatus.BAD_REQUEST

    def test_incomplete_configuration(self) -> None:
        effect = _api("/callback", {"code": "c", "state": "s"}, secrets={}).callback()[0]
        assert effect.status_code == HTTPStatus.SERVICE_UNAVAILABLE

    def test_a_link_token_is_not_a_state(self) -> None:
        link = _pending_link()
        effect = _api("/callback", {"code": "c", "state": link}).callback()[0]
        assert effect.status_code == HTTPStatus.UNAUTHORIZED

    def test_state_for_a_replaced_link(self) -> None:
        _pending_link("nonce-new")
        effect = _api("/callback", {"code": "c", "state": _state("nonce-old")}).callback()[0]
        assert effect.status_code == HTTPStatus.CONFLICT

    @pytest.mark.parametrize("error", [OuraAuthError("bad code"), OuraAPIError(500, "down")])
    def test_failed_exchange_stores_nothing(self, error: Exception) -> None:
        _pending_link()
        with patch("oura_ring_viewer.protocols.oauth_api.build_client", return_value=_client(error=error)):
            effect = _api("/callback", {"code": "c", "state": _state()}).callback()[0]
        assert effect.status_code == HTTPStatus.BAD_GATEWAY
        assert not OuraOAuthToken.objects.filter(patient_id=PATIENT).exists()
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_link_nonce == "nonce-1"
