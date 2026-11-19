"""Patient-facing OAuth bridge: ``/connect`` and ``/callback``.

These routes bypass ``StaffSessionAuthMixin`` because the patient following
the link has no Canvas session. Security comes instead from:

  * the link token: HMAC-SHA256, 3 day expiry, bound to a nonce stored on
    ``OuraSyncState`` so only the most recently issued link works; and
  * the OAuth ``state``: a separately typed signed token carrying the same
    nonce, so the callback is tied to a link this plugin issued.

The nonce is cleared when the callback succeeds, so a completed link cannot be
replayed.

``authenticate`` proves the request carries a token this plugin signed for that
route. It deliberately accepts an expired one: a SimpleAPI authentication
failure can only return bare JSON, and a link that has run out is the most
ordinary failure here, on a patient's phone. Expiry and the single-use nonce
are checked in the handlers, which can answer with a page saying what to do.
Nothing is read or changed for an expired token.

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
from oura_ring_viewer.services.storage import (
    PatientNotFound,
    get_sync_state,
    upsert_sync_state,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class OuraOAuthAPI(SimpleAPI):
    """Patient-facing OAuth bridge, authenticated by signed tokens."""

    def authenticate(self, credentials: Credentials) -> bool:
        """Accept only a request carrying this plugin's signed token for the route."""
        problems = config_problems(self.secrets, OAUTH_SECRETS)
        if problems:
            log.error(f"oura oauth: plugin settings unusable: {', '.join(problems)}")
            return False
        params = self.request.query_params
        secret = self.secrets[MAGIC_LINK_SECRET]
        if self.request.path == "/connect":
            return magic_link.link_is_authentic((params.get("token") or "").strip(), secret)
        if self.request.path == "/callback":
            return magic_link.state_is_authentic((params.get("state") or "").strip(), secret)
        return False

    @api.get("/connect")
    def connect(self) -> list[Response | Effect]:
        """Verify the connection link, then send the patient to Oura's consent page."""
        token = (self.request.query_params.get("token") or "").strip()
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
        if not code:
            return [_page_error("Something went wrong connecting to Oura. Please ask your care "
                                "team for a new link.", HTTPStatus.BAD_REQUEST)]

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

        try:
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
        except PatientNotFound:
            log.warning(f"oura callback for missing patient {claims.patient_id}")
            return [_page_error("We could not find your health record. Please contact your care team.",
                                HTTPStatus.NOT_FOUND)]
        return [_page("templates/connected_success.html", {}, HTTPStatus.OK)]


def _nonce_matches(patient_id: str, nonce: str) -> bool:
    state = get_sync_state(patient_id)
    return bool(state and state.last_link_nonce and state.last_link_nonce == nonce)


def _page(template: str, context: dict[str, str], status: HTTPStatus) -> HTMLResponse:
    return HTMLResponse(content=render_to_string(template, context=context) or "", status_code=status)


def _page_error(message: str, status: HTTPStatus) -> HTMLResponse:
    return _page("templates/connection_error.html", {"message": message}, status)
