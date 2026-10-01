"""OAuth 2.0 (PKCE) authorization-code flow for the Salesforce External Client App.

Two endpoints:

* ``GET /oauth/start``    — generates a PKCE pair, stores the verifier under
  the returned ``state`` value, then redirects the staff member to Salesforce.
* ``GET /oauth/callback`` — receives the auth code from Salesforce, exchanges
  it for access + refresh tokens, persists them, and redirects the staff back
  to the admin application.

Both endpoints are restricted to logged-in Canvas staff members whose ids
appear in ``SF_ADMIN_STAFF_IDS``.
"""

import base64
import hashlib
import uuid
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

from canvas_sdk.caching.plugins import get_cache
from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import (
    SessionCredentials,
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.utils.http import Http
from logger import log

from salesforce_to_canvas_integration.services.config import ConfigError, load_config
from salesforce_to_canvas_integration.services.sf_client import (
    SalesforceClient,
    SalesforceError,
)
from salesforce_to_canvas_integration.services.storage import TokenStore

OAUTH_STATE_PREFIX = "oauth:state:"
OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes is plenty for a redirect round-trip
OAUTH_SCOPES = "api refresh_token offline_access"
ADMIN_APP_PATH = "/plugin-io/api/salesforce_to_canvas_integration/admin"


def _b64url(raw: bytes) -> str:
    """URL-safe base64 without padding, built from plain b64encode.

    The sandbox blocks ``base64.urlsafe_b64encode``, so we encode with the
    standard alphabet and then swap the two differing characters.
    """
    encoded = base64.b64encode(raw).decode("ascii")
    return encoded.replace("+", "-").replace("/", "_").rstrip("=")


def _random_token(nbytes: int) -> str:
    """Cryptographically random URL-safe token of approximately ``nbytes`` of entropy.

    ``uuid.uuid4()`` is backed by ``os.urandom`` and yields 16 bytes per call,
    so we chain calls until we have enough material.
    """
    chunks: list[bytes] = []
    needed = nbytes
    while needed > 0:
        chunks.append(uuid.uuid4().bytes)
        needed -= 16
    raw = b"".join(chunks)[:nbytes]
    return _b64url(raw)


def _build_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)``."""
    verifier = _random_token(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = _b64url(digest)
    return verifier, challenge


def _callback_url(request: Any) -> str:
    """Derive the absolute callback URL from the inbound request host header.

    SimpleAPI does not expose a base URL helper, but the ``Host`` header is
    set by Canvas's edge so this is reliable enough for the redirect.
    """
    host = request.headers.get("Host") or request.headers.get("X-Forwarded-Host")
    proto = request.headers.get("X-Forwarded-Proto", "https")
    if not host:
        raise SalesforceError("Cannot derive callback URL — no Host header on request")
    return f"{proto}://{host}/plugin-io/api/salesforce_to_canvas_integration/oauth/callback"


class SalesforceOAuthAPI(StaffSessionAuthMixin, SimpleAPI):
    """Authorization-Code-with-PKCE flow against a Salesforce External Client App."""

    def authenticate(self, credentials: SessionCredentials) -> bool:
        if not super().authenticate(credentials):
            return False
        staff_id = str(credentials.logged_in_user.get("id") or "")
        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            log.warning("OAuth endpoint denied: %s", exc)
            return False
        return staff_id in config.admin_staff_ids

    @api.get("/oauth/start")
    def start(self) -> list[Response | Effect]:
        try:
            config = load_config(self.secrets)
            redirect_uri = _callback_url(self.request)
        except (ConfigError, SalesforceError) as exc:
            return [
                JSONResponse(
                    content={"error": str(exc)},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                ).apply()
            ]

        verifier, challenge = _build_pkce_pair()
        state = _random_token(24)
        cache = get_cache()
        cache.set(
            f"{OAUTH_STATE_PREFIX}{state}",
            {"verifier": verifier, "redirect_uri": redirect_uri},
            timeout_seconds=OAUTH_STATE_TTL_SECONDS,
        )

        authorize_url = (
            f"{config.login_url}/services/oauth2/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": config.client_id,
                    "redirect_uri": redirect_uri,
                    "scope": OAUTH_SCOPES,
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

        return [
            JSONResponse(
                content={"authorize_url": authorize_url},
                status_code=HTTPStatus.OK,
                headers={"Location": authorize_url, "Cache-Control": "no-store"},
            ).apply()
        ]

    @api.get("/oauth/callback")
    def callback(self) -> list[Response | Effect]:
        params = self.request.query_params

        if "error" in params:
            return [
                JSONResponse(
                    content={"error": params.get("error_description") or params.get("error")},
                    status_code=HTTPStatus.BAD_REQUEST,
                ).apply()
            ]

        code = params.get("code")
        state = params.get("state")
        if not code or not state:
            return [
                JSONResponse(
                    content={"error": "Missing code or state"},
                    status_code=HTTPStatus.BAD_REQUEST,
                ).apply()
            ]

        cache = get_cache()
        stash = cache.get(f"{OAUTH_STATE_PREFIX}{state}")
        if not isinstance(stash, dict):
            return [
                JSONResponse(
                    content={"error": "OAuth state expired — please reconnect"},
                    status_code=HTTPStatus.BAD_REQUEST,
                ).apply()
            ]
        cache.delete(f"{OAUTH_STATE_PREFIX}{state}")

        try:
            config = load_config(self.secrets)
        except ConfigError as exc:
            return [
                JSONResponse(
                    content={"error": str(exc)},
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                ).apply()
            ]

        client = SalesforceClient(
            http=Http(),
            tokens=TokenStore(cache),
            login_url=config.login_url,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )
        try:
            client.exchange_authorization_code(
                code=code,
                redirect_uri=str(stash["redirect_uri"]),
                code_verifier=str(stash["verifier"]),
            )
        except SalesforceError as exc:
            log.warning("Salesforce OAuth callback failed: %s", exc)
            return [
                JSONResponse(
                    content={"error": str(exc)},
                    status_code=HTTPStatus.BAD_GATEWAY,
                ).apply()
            ]

        return [
            JSONResponse(
                content={"status": "connected"},
                status_code=HTTPStatus.OK,
                headers={"Location": ADMIN_APP_PATH, "Cache-Control": "no-store"},
            ).apply()
        ]
