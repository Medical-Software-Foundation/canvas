"""Patient-facing OAuth bridge: ``/connect`` and ``/callback``.

These routes bypass ``StaffSessionAuthMixin`` because the patient following
the link has no Canvas session. Security comes instead from:

  * the link token: HMAC-SHA256, 3 day expiry, bound to a nonce stored on
    ``OuraSyncState`` so only the most recently issued link works; and
  * the OAuth ``state``: a separately typed signed token carrying the same
    nonce, so the callback is tied to a link this plugin issued.

The nonce is cleared when the callback succeeds, so a completed link cannot be
replayed. ``authenticate`` always returns True and each handler validates its
own token, which is how an unauthenticated public callback is expressed under
the Canvas SimpleAPI auth model.

Every response is a human-readable page: the patient arrives from their phone,
not from the chart.
"""

import datetime as dt
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, api
from canvas_sdk.handlers.simple_api.security import Credentials
from canvas_sdk.templates import render_to_string
from logger import log

from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.config import (
    MAGIC_LINK_SECRET,
    OAUTH_SECRETS,
    build_client,
    config_problems,
)
from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.oauth import persist_tokens
from oura_ring_viewer.services.oura_client import OuraAPIError, OuraAuthError
from oura_ring_viewer.services.storage import get_sync_state, upsert_sync_state


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class OuraOAuthAPI(SimpleAPI):
    """Patient-facing OAuth bridge. Auth happens per handler via signed tokens."""

    def authenticate(self, credentials: Credentials) -> bool:
        """Always accept; each handler validates its own token."""
        return True

    @api.get("/connect")
    def connect(self) -> list[Response | Effect]:
        """Verify the connection link, then send the patient to Oura's consent page."""
        token = (self.request.query_params.get("token") or "").strip()
        if not token:
            return [_page_error("This link is incomplete. Please ask your care team for a new one.",
                                HTTPStatus.BAD_REQUEST)]
        if config_problems(self.secrets, OAUTH_SECRETS):
            log.error("oura connect: plugin settings incomplete")
            return [_page_error("Connecting is not available right now. Please contact your care team.",
                                HTTPStatus.SERVICE_UNAVAILABLE)]

        now = _now()
        secret = self.secrets[MAGIC_LINK_SECRET]
        try:
            claims = magic_link.verify_link(token, secret, now=int(now.timestamp()))
        except magic_link.InvalidToken as exc:
            log.warning(f"oura connect link rejected: {exc}")
            return [_page_error("This link has expired or is not valid. Please ask your care "
                                "team for a new one.", HTTPStatus.UNAUTHORIZED)]

        if not _nonce_matches(claims.patient_id, claims.nonce):
            return [_page_error("This link has already been used or replaced by a newer one. "
                                "Please ask your care team for a new one.", HTTPStatus.CONFLICT)]

        state = magic_link.sign_state(claims.patient_id, claims.nonce, secret, now=int(now.timestamp()))
        location = build_client(self.secrets).authorize_url(state)
        return [Response(status_code=HTTPStatus.FOUND, headers={"Location": location})]

    @api.get("/callback")
    def callback(self) -> list[Response | Effect]:
        """Exchange the authorization code for tokens and store them."""
        params = self.request.query_params
        if params.get("error"):
            # The patient declined on Oura's consent screen. Not a failure of
            # ours, so it gets a calm page and a normal status.
            return [_page("templates/connection_error.html", {
                "message": "You chose not to share your Oura data. Nothing was connected. "
                           "If that was a mistake, ask your care team for a new link.",
            }, HTTPStatus.OK)]

        code = (params.get("code") or "").strip()
        state = (params.get("state") or "").strip()
        if not code or not state:
            return [_page_error("Something went wrong connecting to Oura. Please ask your care "
                                "team for a new link.", HTTPStatus.BAD_REQUEST)]
        if config_problems(self.secrets, OAUTH_SECRETS):
            log.error("oura callback: plugin settings incomplete")
            return [_page_error("Connecting is not available right now. Please contact your care team.",
                                HTTPStatus.SERVICE_UNAVAILABLE)]

        now = _now()
        try:
            claims = magic_link.verify_state(state, self.secrets[MAGIC_LINK_SECRET],
                                             now=int(now.timestamp()))
        except magic_link.InvalidToken as exc:
            log.warning(f"oura callback state rejected: {exc}")
            return [_page_error("This connection attempt has expired. Please ask your care team "
                                "for a new link.", HTTPStatus.UNAUTHORIZED)]

        if not _nonce_matches(claims.patient_id, claims.nonce):
            return [_page_error("This connection has already been completed or replaced. "
                                "If your data is not showing, ask your care team for a new link.",
                                HTTPStatus.CONFLICT)]

        try:
            tokens = build_client(self.secrets).exchange_code(code)
        except (OuraAuthError, OuraAPIError) as exc:
            log.warning(f"oura code exchange failed: {type(exc).__name__}")
            return [_page_error("Oura did not complete the connection. Please try the link again, "
                                "or ask your care team for a new one.", HTTPStatus.BAD_GATEWAY)]

        persist_tokens(claims.patient_id, TokenCipher(), tokens, is_initial_connection=True, now=now)
        # Burn the nonce so this link and state cannot be replayed, and clear
        # any earlier reconnect-required error so the chart shows "connected".
        upsert_sync_state(
            claims.patient_id,
            last_link_nonce="",
            link_pending=False,
            last_error="",
            last_error_at=None,
        )
        return [_page("templates/connected_success.html", {}, HTTPStatus.OK)]


def _nonce_matches(patient_id: str, nonce: str) -> bool:
    state = get_sync_state(patient_id)
    return bool(state and state.last_link_nonce and state.last_link_nonce == nonce)


def _page(template: str, context: dict[str, str], status: HTTPStatus) -> HTMLResponse:
    return HTMLResponse(content=render_to_string(template, context=context) or "", status_code=status)


def _page_error(message: str, status: HTTPStatus) -> HTMLResponse:
    return _page("templates/connection_error.html", {"message": message}, status)
