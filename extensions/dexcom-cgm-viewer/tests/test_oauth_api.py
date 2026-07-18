"""Patient-facing OAuth bridge: ``/connect`` and ``/callback``."""

from __future__ import annotations

import datetime as dt
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api.security import Credentials
from dexcom_cgm_viewer.services import magic_link, storage
from dexcom_cgm_viewer.services.dexcom_client import DexcomAPIError, DexcomAuthError, TokenSet
from dexcom_cgm_viewer.protocols.oauth_api import (
    DexcomOAuthAPI,
    _missing_secrets,
)


PATIENT = "patient-oauth-1"
MAGIC_SECRET = "x" * 64


@pytest.fixture(autouse=True)
def _stub_render_to_string() -> Any:
    """``render_to_string`` requires a real plugin runtime ancestor frame to
    locate the plugin's templates dir. In unit tests we stub it to echo back
    the rendered message so the patient-facing copy is still asserted on."""
    def fake_render(template: str, context: dict | None = None) -> str:
        ctx = context or {}
        if "message" in ctx:
            return f"<html><body>{ctx['message']}</body></html>"
        return "<html><body>connected</body></html>"

    with patch(
        "dexcom_cgm_viewer.protocols.oauth_api.render_to_string",
        side_effect=fake_render,
    ):
        yield


def _now() -> dt.datetime:
    return dt.datetime(2026, 5, 6, 12, 0, tzinfo=dt.timezone.utc)


def _full_secrets() -> dict[str, str]:
    return {
        "DEXCOM_CLIENT_ID": "cid",
        "DEXCOM_CLIENT_SECRET": "csec",
        "DEXCOM_REDIRECT_URI": "https://canvas.example.com/plugin-io/api/dexcom_cgm_viewer/callback",
        "DEXCOM_ENVIRONMENT": "sandbox",
        "DEXCOM_MAGIC_LINK_SECRET": MAGIC_SECRET,
    }


class DummyRequest:
    def __init__(
        self,
        *,
        query_params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.query_params = query_params or {}
        self.headers = headers or {}


class DummyEvent:
    def __init__(self, context: dict[str, Any] | None = None) -> None:
        self.context = context or {"method": "GET", "path": "/connect"}


def _make_api(
    path: str,
    query_params: dict[str, str] | None = None,
    *,
    secrets: dict[str, str] | None = None,
) -> DexcomOAuthAPI:
    api = DexcomOAuthAPI(event=DummyEvent(context={"method": "GET", "path": path}))
    api.request = DummyRequest(query_params=query_params)
    api.secrets = secrets if secrets is not None else _full_secrets()
    return api


def _seed_pending_link(nonce: str) -> None:
    storage.upsert_sync_state(PATIENT, last_link_nonce=nonce, link_pending=True)


def _html_text(effects: list[Any]) -> str:
    """Decode the body of an HTMLResponse. The patient-facing error pages
    render an ``{{ message }}`` substring directly into the template."""
    response = effects[0]
    assert isinstance(response, HTMLResponse)
    content = response.content
    return content.decode("utf-8") if isinstance(content, bytes) else str(content)


# ---- authenticate (always-allow) --------------------------------------------


def test_authenticate_returns_true() -> None:
    api = _make_api("/connect")
    assert api.authenticate(Credentials(MagicMock())) is True


# ---- /connect ---------------------------------------------------------------


def test_connect_rejects_missing_token() -> None:
    api = _make_api("/connect", query_params={})
    effects = api.connect()
    assert isinstance(effects[0], HTMLResponse)
    assert "missing a token" in _html_text(effects)


def test_connect_503_when_secrets_missing() -> None:
    api = _make_api("/connect", query_params={"token": "anything"}, secrets={})
    effects = api.connect()
    assert effects[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_connect_rejects_invalid_token() -> None:
    api = _make_api("/connect", query_params={"token": "not-a-real-token"})
    effects = api.connect()
    assert isinstance(effects[0], HTMLResponse)
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED
    assert "invalid" in _html_text(effects)


def test_connect_rejects_token_with_no_pending_link() -> None:
    import time
    token, _nonce = magic_link.mint(PATIENT, MAGIC_SECRET, now=int(time.time()))
    api = _make_api("/connect", query_params={"token": token})
    effects = api.connect()
    assert isinstance(effects[0], HTMLResponse)
    assert effects[0].status_code == HTTPStatus.CONFLICT
    assert "already been used" in _html_text(effects)


def test_connect_redirects_to_dexcom() -> None:
    import time
    token, nonce = magic_link.mint(PATIENT, MAGIC_SECRET, now=int(time.time()))
    _seed_pending_link(nonce)
    api = _make_api("/connect", query_params={"token": token})
    effects = api.connect()
    response = effects[0]
    assert response.status_code == HTTPStatus.FOUND
    location = response.headers.get("Location")
    assert location is not None
    assert location.startswith("https://sandbox-api.dexcom.com/v3/oauth2/login?")
    assert "client_id=cid" in location
    assert "scope=offline_access" in location


def test_connect_rejects_when_stored_nonce_differs() -> None:
    import time as time_mod
    token, _ = magic_link.mint(PATIENT, MAGIC_SECRET, now=int(time_mod.time()))
    _seed_pending_link("a-different-nonce")
    api = _make_api("/connect", query_params={"token": token})
    effects = api.connect()
    assert effects[0].status_code == HTTPStatus.CONFLICT


# ---- /callback --------------------------------------------------------------


def test_callback_rejects_missing_params() -> None:
    api = _make_api("/callback", query_params={})
    effects = api.callback()
    assert isinstance(effects[0], HTMLResponse)
    assert "Missing OAuth" in _html_text(effects)


def test_callback_503_when_secrets_missing() -> None:
    api = _make_api("/callback", query_params={"code": "c", "state": "s"}, secrets={})
    effects = api.callback()
    assert effects[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_callback_rejects_tampered_state() -> None:
    api = _make_api("/callback", query_params={"code": "c", "state": "garbage"})
    effects = api.callback()
    assert effects[0].status_code == HTTPStatus.UNAUTHORIZED


def test_callback_rejects_when_nonce_already_burned() -> None:
    state = magic_link.sign_state(PATIENT, "nonce-A", MAGIC_SECRET)
    _seed_pending_link("a-different-nonce")
    api = _make_api("/callback", query_params={"code": "c", "state": state})
    effects = api.callback()
    assert effects[0].status_code == HTTPStatus.CONFLICT


def test_callback_returns_502_when_dexcom_token_exchange_fails() -> None:
    state = magic_link.sign_state(PATIENT, "nonce-A", MAGIC_SECRET)
    _seed_pending_link("nonce-A")
    api = _make_api("/callback", query_params={"code": "c", "state": state})
    fake_client = MagicMock()
    fake_client.exchange_code.side_effect = DexcomAuthError("rejected")
    with patch("dexcom_cgm_viewer.protocols.oauth_api._build_client", return_value=fake_client):
        effects = api.callback()
    assert effects[0].status_code == HTTPStatus.BAD_GATEWAY


def test_callback_returns_502_when_dexcom_returns_api_error() -> None:
    state = magic_link.sign_state(PATIENT, "nonce-A", MAGIC_SECRET)
    _seed_pending_link("nonce-A")
    api = _make_api("/callback", query_params={"code": "c", "state": state})
    fake_client = MagicMock()
    fake_client.exchange_code.side_effect = DexcomAPIError(503, "down")
    with patch("dexcom_cgm_viewer.protocols.oauth_api._build_client", return_value=fake_client):
        effects = api.callback()
    assert effects[0].status_code == HTTPStatus.BAD_GATEWAY


def test_callback_returns_502_when_dexcom_returns_empty_tokens() -> None:
    state = magic_link.sign_state(PATIENT, "nonce-A", MAGIC_SECRET)
    _seed_pending_link("nonce-A")
    api = _make_api("/callback", query_params={"code": "c", "state": state})
    fake_client = MagicMock()
    fake_client.exchange_code.return_value = TokenSet(
        access_token="", refresh_token="", expires_in=0,
        token_type="Bearer", dexcom_user_id="",
    )
    with patch("dexcom_cgm_viewer.protocols.oauth_api._build_client", return_value=fake_client):
        effects = api.callback()
    assert effects[0].status_code == HTTPStatus.BAD_GATEWAY


def test_callback_persists_tokens_and_burns_nonce_on_success() -> None:
    state = magic_link.sign_state(PATIENT, "nonce-A", MAGIC_SECRET)
    _seed_pending_link("nonce-A")
    api = _make_api("/callback", query_params={"code": "c", "state": state})
    fake_client = MagicMock()
    fake_client.exchange_code.return_value = TokenSet(
        access_token="AT", refresh_token="RT", expires_in=7200,
        token_type="Bearer", dexcom_user_id="DEX-USER",
    )
    with patch("dexcom_cgm_viewer.protocols.oauth_api._build_client", return_value=fake_client):
        effects = api.callback()
    assert isinstance(effects[0], HTMLResponse)
    assert storage.get_tokens(PATIENT) is not None
    state_row = storage.get_sync_state(PATIENT)
    assert state_row is not None
    assert state_row.last_link_nonce == ""
    assert state_row.link_pending is False


def test_callback_clears_prior_refresh_failed_state() -> None:
    """Regression: a permanent refresh failure pins the chart UI to its
    "expired" branch, which only offers a "Generate connection link"
    button. The patient re-onboards via that flow → /callback runs and
    persists fresh tokens. If callback didn't *also* clear last_error,
    chart_data._resolve_status would still see ``has_tokens AND last_error
    == 'refresh_failed'`` → still "expired" → staff is stuck in the same
    single-button UI even though the patient is actually re-connected."""
    from dexcom_cgm_viewer.services import chart_data as _chart_data

    # Seed a stale refresh_failed state from a prior permanent failure.
    storage.upsert_sync_state(
        PATIENT,
        last_link_nonce="nonce-B",
        link_pending=True,
        last_error="refresh_failed",
        last_error_at=_now(),
    )

    state = magic_link.sign_state(PATIENT, "nonce-B", MAGIC_SECRET)
    api = _make_api("/callback", query_params={"code": "c", "state": state})
    fake_client = MagicMock()
    fake_client.exchange_code.return_value = TokenSet(
        access_token="AT-NEW", refresh_token="RT-NEW", expires_in=7200,
        token_type="Bearer", dexcom_user_id="DEX",
    )
    with patch("dexcom_cgm_viewer.protocols.oauth_api._build_client", return_value=fake_client):
        api.callback()

    state_row = storage.get_sync_state(PATIENT)
    assert state_row is not None
    assert state_row.last_error == ""
    assert state_row.last_error_at is None

    # End-to-end: chart_data._resolve_status no longer reports "expired" —
    # the UI escapes the single-button loop.
    payload = _chart_data.build_payload(PATIENT, range_days=14, now=_now())
    assert payload.connection_status == "connected"


# ---- helpers ----------------------------------------------------------------


def test_missing_secrets_lists_every_required_when_empty() -> None:
    assert "DEXCOM_CLIENT_ID" in _missing_secrets({})
    assert "DEXCOM_CLIENT_ID" in _missing_secrets(None)


def test_missing_secrets_returns_empty_when_full() -> None:
    assert _missing_secrets(_full_secrets()) == ""


def test_html_error_returns_html_response_with_message_rendered() -> None:
    """The patient lands on /connect or /callback from an SMS link on their
    phone with no Canvas session — error responses must be HTML, not JSON
    (otherwise the browser renders raw `{"error": "..."}` as plain text)."""
    from dexcom_cgm_viewer.protocols.oauth_api import _html_error
    response = _html_error("This link has expired.", HTTPStatus.UNAUTHORIZED)
    assert isinstance(response, HTMLResponse)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    body = response.content
    text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    assert "This link has expired." in text
    # Stubbed render_to_string wraps the message in an HTML body so the
    # contract — HTML out, not JSON — is observable here too.
    assert text.lstrip().startswith("<")
