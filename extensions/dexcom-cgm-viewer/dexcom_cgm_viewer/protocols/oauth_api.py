"""Patient-facing OAuth bridge: ``/connect`` and ``/callback``.

These routes intentionally bypass ``StaffSessionAuthMixin`` because the
patient who taps the SMS link is not authenticated to Canvas. Security comes
from:

  * the magic-link JWT (HMAC-SHA256, 15-min expiry, single-use nonce); and
  * the OAuth ``state`` parameter on the callback (signed patient_id+nonce).

The plugin's ``authenticate`` always returns ``True``; per-route validation
runs inside each handler. This is the idiomatic way to do unauthenticated
public callback endpoints with the Canvas SimpleAPI auth model.
"""

import datetime as dt
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import (
    HTMLResponse,
    Response,
)
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import Credentials
from canvas_sdk.templates import render_to_string
from logger import log

from dexcom_cgm_viewer.lib.crypto import TokenCipher
from dexcom_cgm_viewer.lib.dexcom_client import (
    DexcomAPIError,
    DexcomAuthError,
    DexcomClient,
)
from dexcom_cgm_viewer.lib.magic_link import (
    sign_state as sign_oauth_state,
    verify as verify_magic_link,
    verify_state,
)
from dexcom_cgm_viewer.lib.oauth import persist_tokens
from dexcom_cgm_viewer.lib.settings import REQUIRED_SECRETS
from dexcom_cgm_viewer.lib.storage import get_sync_state, upsert_sync_state


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class DexcomOAuthAPI(SimpleAPI):
    """Patient-facing OAuth bridge. Auth happens per-handler via JWT/state."""

    def authenticate(self, credentials: Credentials) -> bool:
        """Always accept the request — handlers validate their own tokens."""
        return True

    @api.get("/connect")
    def connect(self) -> list[Response | Effect]:
        """Validate the magic-link JWT and 302 to Dexcom hosted login."""
        token = (self.request.query_params.get("token") or "").strip()
        if not token:
            return [_html_error("This link is missing a token.", HTTPStatus.BAD_REQUEST)]

        secrets_check = _missing_secrets(self.secrets)
        if secrets_check:
            log.error(f"send-link bypass: missing plugin secrets {secrets_check}")
            return [_html_error("Plugin is not fully configured.", HTTPStatus.SERVICE_UNAVAILABLE)]

        magic_secret = self.secrets["DEXCOM_MAGIC_LINK_SECRET"]
        try:
            claims = verify_magic_link(token, magic_secret, now=int(_now().timestamp()))
        except ValueError as exc:
            log.warning(f"magic-link rejected: {exc}")
            return [_html_error("This connection link is invalid or expired.", HTTPStatus.UNAUTHORIZED)]

        state_row = get_sync_state(claims.patient_id)
        stored_nonce = state_row.last_link_nonce if state_row else ""
        if not stored_nonce or stored_nonce != claims.nonce:
            return [_html_error(
                "This connection link has already been used. Please request a new one.",
                HTTPStatus.CONFLICT,
            )]

        client = _build_client(self.secrets)
        state_value = sign_oauth_state(claims.patient_id, claims.nonce, magic_secret)
        return [Response(
            status_code=HTTPStatus.FOUND,
            headers={"Location": client.authorize_url(state_value)},
        )]

    @api.get("/callback")
    def callback(self) -> list[Response | Effect]:
        """Exchange the authorization code for tokens and store them encrypted."""
        code = (self.request.query_params.get("code") or "").strip()
        state = (self.request.query_params.get("state") or "").strip()
        if not code or not state:
            return [_html_error("Missing OAuth parameters.", HTTPStatus.BAD_REQUEST)]

        secrets_check = _missing_secrets(self.secrets)
        if secrets_check:
            log.error(f"oauth callback: missing plugin secrets {secrets_check}")
            return [_html_error("Plugin is not fully configured.", HTTPStatus.SERVICE_UNAVAILABLE)]

        try:
            patient_id, nonce = verify_state(
                state, self.secrets["DEXCOM_MAGIC_LINK_SECRET"],
            )
        except ValueError as exc:
            log.warning(f"oauth state rejected: {exc}")
            return [_html_error("OAuth state mismatch.", HTTPStatus.UNAUTHORIZED)]

        state_row = get_sync_state(patient_id)
        stored_nonce = state_row.last_link_nonce if state_row else ""
        if not stored_nonce or stored_nonce != nonce:
            return [_html_error("OAuth flow expired or already completed.", HTTPStatus.CONFLICT)]

        client = _build_client(self.secrets)
        try:
            tokens = client.exchange_code(code)
        except (DexcomAuthError, DexcomAPIError):
            log.exception("dexcom code exchange failed")
            return [_html_error("Could not connect with Dexcom. Please try again.", HTTPStatus.BAD_GATEWAY)]
        if not tokens.access_token or not tokens.refresh_token:
            return [_html_error("Dexcom returned an incomplete token response.", HTTPStatus.BAD_GATEWAY)]

        cipher = TokenCipher()
        now = _now()
        persist_tokens(patient_id, cipher, tokens, is_initial_connection=True, now=now)

        # Burn the nonce so the magic link can't be reused, and clear any
        # prior auth-related error state. A previous refresh-token failure
        # would otherwise pin chart_data._resolve_status to "expired", whose
        # only UI action is "Generate connection link" — the patient would
        # be stuck in a loop because the post-callback chart UI would still
        # offer only the same magic-link button they just used.
        upsert_sync_state(
            patient_id,
            last_link_nonce="",
            link_pending=False,
            last_error="",
            last_error_at=None,
        )

        return [HTMLResponse(
            content=render_to_string(
                "templates/connected_success.html",
                context={},
            ),
            status_code=HTTPStatus.OK,
        )]


def _build_client(secrets: dict[str, str]) -> DexcomClient:
    """Construct a ``DexcomClient`` for OAuth round-trips."""
    return DexcomClient(
        environment=secrets["DEXCOM_ENVIRONMENT"],
        client_id=secrets["DEXCOM_CLIENT_ID"],
        client_secret=secrets["DEXCOM_CLIENT_SECRET"],
        redirect_uri=secrets["DEXCOM_REDIRECT_URI"],
    )


def _missing_secrets(secrets: dict[str, str] | None) -> str:
    """Return a comma-separated list of missing required secret keys."""
    if not secrets:
        return ", ".join(REQUIRED_SECRETS)
    missing = [name for name in REQUIRED_SECRETS if not secrets.get(name)]
    return ", ".join(missing)


def _html_error(message: str, status_code: HTTPStatus) -> HTMLResponse:
    """Render a patient-friendly HTML error page.

    The patient lands on these endpoints from an SMS / email link on their
    phone, with no Canvas session — so the response has to be a human-
    readable page, not raw JSON. The template mirrors
    ``connected_success.html`` so success and failure share visual style.
    """
    return HTMLResponse(
        content=render_to_string(
            "templates/connection_error.html",
            context={"message": message},
        ),
        status_code=status_code,
    )
