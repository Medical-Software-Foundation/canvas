"""Tests for the patient portal API, against real tables and real templates."""

import datetime as dt
import json
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse

from oura_ring_viewer.protocols.portal_api import OuraPortalAPI
from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.storage import (
    get_sync_state,
    get_tokens,
    upsert_sync_state,
    upsert_tokens,
)

PATIENT = "pat123"
SECRETS = {
    "OURA_CLIENT_ID": "cid",
    "OURA_CLIENT_SECRET": "sec",
    "OURA_REDIRECT_URI": "https://acme.canvasmedical.com/plugin-io/api/oura_ring_viewer/callback",
    "OURA_ENVIRONMENT": "sandbox",
    "OURA_MAGIC_LINK_SECRET": "m" * 40,
}
HEADERS = {"canvas-logged-in-user-type": "Patient", "canvas-logged-in-user-id": PATIENT}


class _Request:
    def __init__(self, headers: dict[str, str]) -> None:
        self.query_params: dict[str, str] = {}
        self.headers = headers


class _Event:
    def __init__(self, method: str, path: str) -> None:
        self.context = {"method": method, "path": path}


def _api(method: str, path: str, *, headers: dict[str, str] | None = None,
         secrets: dict[str, str] | None = None) -> OuraPortalAPI:
    handler = OuraPortalAPI(event=_Event(method, f"/portal{path}"))
    handler.request = _Request(HEADERS if headers is None else headers)
    handler.secrets = SECRETS if secrets is None else secrets
    return handler


def _json(effect: Any) -> Any:
    assert isinstance(effect, JSONResponse)
    return json.loads(effect.content)


def _connect(patient_id: str = PATIENT) -> None:
    now = dt.datetime.now(dt.UTC)
    upsert_tokens(patient_id, access_token_ciphertext="AT", refresh_token_ciphertext="RT",
                  expires_at=now + dt.timedelta(hours=1), scopes="daily spo2", now=now,
                  is_initial_connection=True)


def _state_nonce(location: str) -> str:
    state = parse_qs(urlparse(location).query)["state"][0]
    claims = magic_link.verify_state(state, SECRETS["OURA_MAGIC_LINK_SECRET"])
    assert claims.patient_id == PATIENT
    return claims.nonce


class TestPage:
    def test_renders_with_connect_available(self) -> None:
        effect = _api("GET", "/").page()[0]
        assert isinstance(effect, HTMLResponse)
        html = effect.content.decode()
        assert 'var API = "/plugin-io/api/oura_ring_viewer/portal";' in html
        assert "var AVAILABLE = true;" in html
        assert "<script src=" not in html

    def test_says_when_connecting_is_unavailable(self) -> None:
        html = _api("GET", "/", secrets={}).page()[0].content.decode()
        assert "var AVAILABLE = false;" in html

    def test_without_an_identifiable_patient(self) -> None:
        effect = _api("GET", "/", headers={"canvas-logged-in-user-id": "bad id"}).page()[0]
        assert effect.status_code == HTTPStatus.BAD_REQUEST


class TestStatus:
    def test_not_connected(self) -> None:
        assert _json(_api("GET", "/status").status()[0]) == {"status": "not_connected", "connected_at": None}

    def test_connected(self) -> None:
        _connect()
        body = _json(_api("GET", "/status").status()[0])
        assert body["status"] == "connected"
        assert body["connected_at"] is not None

    def test_dead_tokens_ask_for_reconnect(self) -> None:
        _connect()
        upsert_sync_state(PATIENT, last_error="refresh_failed")
        assert _json(_api("GET", "/status").status()[0])["status"] == "reconnect"

    def test_only_ever_the_signed_in_patient(self) -> None:
        _connect("someone-else")
        assert _json(_api("GET", "/status").status()[0])["status"] == "not_connected"

    def test_without_an_identifiable_patient(self) -> None:
        effect = _api("GET", "/status", headers={}).status()[0]
        assert effect.status_code == HTTPStatus.BAD_REQUEST


class TestStart:
    def test_redirects_to_oura_with_a_state_bound_to_a_fresh_nonce(self) -> None:
        effect = _api("GET", "/start").start()[0]
        assert effect.status_code == HTTPStatus.FOUND
        location = effect.headers["Location"]
        assert location.startswith("https://cloud.ouraring.com/oauth/authorize?")
        nonce = _state_nonce(location)
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_link_nonce == nonce
        assert state.link_pending is False, "starting from the portal is not a staff link"

    def test_reuses_a_live_staff_link_so_it_keeps_working(self) -> None:
        upsert_sync_state(PATIENT, last_link_nonce="staff-nonce", link_pending=True,
                          last_link_sent_at=dt.datetime.now(dt.UTC))
        location = _api("GET", "/start").start()[0].headers["Location"]
        assert _state_nonce(location) == "staff-nonce"
        state = get_sync_state(PATIENT)
        assert state is not None and state.last_link_nonce == "staff-nonce"

    def test_an_expired_staff_link_is_not_reused(self) -> None:
        upsert_sync_state(PATIENT, last_link_nonce="old", link_pending=True,
                          last_link_sent_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=4))
        location = _api("GET", "/start").start()[0].headers["Location"]
        assert _state_nonce(location) != "old"

    def test_refuses_when_settings_are_incomplete(self) -> None:
        effect = _api("GET", "/start", secrets={"OURA_ENVIRONMENT": "sandbox"}).start()[0]
        assert effect.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert get_sync_state(PATIENT) is None

    def test_without_an_identifiable_patient(self) -> None:
        effect = _api("GET", "/start", headers={}).start()[0]
        assert effect.status_code == HTTPStatus.BAD_REQUEST


class TestStopSharing:
    def test_removes_only_the_patients_own_connection(self) -> None:
        _connect()
        _connect("someone-else")
        assert _json(_api("POST", "/disconnect").disconnect()[0]) == {"disconnected": True}
        assert get_tokens(PATIENT) is None
        assert get_tokens("someone-else") is not None

    def test_without_an_identifiable_patient(self) -> None:
        effect = _api("POST", "/disconnect", headers={}).disconnect()[0]
        assert effect.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.parametrize("user_type", ["Staff", ""])
def test_only_patients_are_admitted(user_type: str) -> None:
    from canvas_sdk.handlers.simple_api.security import (
        InvalidCredentialsError,
        SessionCredentials,
    )

    handler = _api("GET", "/status", headers={"canvas-logged-in-user-type": user_type,
                                               "canvas-logged-in-user-id": PATIENT})
    credentials = SessionCredentials.__new__(SessionCredentials)
    credentials.logged_in_user = {"id": PATIENT, "type": user_type}
    with pytest.raises(InvalidCredentialsError):
        handler.authenticate(credentials)
