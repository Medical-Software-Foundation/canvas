"""Patient-session SimpleAPI behind the "Oura Ring" portal menu item.

Routes (all under ``/portal``):
  GET  /           -> the patient's own page
  GET  /static/<asset> -> the page's own CSS and JS, no patient data
  GET  /status     -> JSON: is this patient connected
  GET  /start      -> begin the Oura consent flow (opened in a new tab)
  POST /disconnect -> stop sharing: end access at Oura, remove tokens and status

``PatientSessionAuthMixin`` admits only a signed-in patient, and the patient is
always the one named by the Canvas-set session header, never a query
parameter, so a patient can only ever act on their own connection. A login
acting for someone else, such as a parent, is refused because this handler
declares no ``PORTAL_ACCESS``; connecting a wearable is the patient's own
decision.

``/start`` reuses the nonce of a staff link that is still out, so a patient who
starts here does not cancel the link their care team sent, and vice versa.
"""

import datetime as dt
from http import HTTPStatus

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import PatientSessionAuthMixin, SimpleAPI, api
from canvas_sdk.templates import render_to_string
from logger import log

from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.assets import PORTAL_ASSETS
from oura_ring_viewer.services.chart_data import (
    STATUS_CONNECTED,
    STATUS_EXPIRED,
    connection_status,
)
from oura_ring_viewer.services.config import (
    MAGIC_LINK_SECRET,
    OAUTH_SECRETS,
    build_client,
    clean_patient_id,
    config_problems,
)
from oura_ring_viewer.services.disconnect import stop_sharing
from oura_ring_viewer.services.links import live_link_nonce
from oura_ring_viewer.services.settings import PLUGIN_API_PATH
from oura_ring_viewer.services.storage import (
    get_sync_state,
    get_tokens,
    upsert_sync_state,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class OuraPortalAPI(PatientSessionAuthMixin, SimpleAPI):
    """The signed-in patient's own Oura connection."""

    PREFIX = "/portal"

    @api.get("/")
    def page(self) -> list[Response | Effect]:
        """Render the patient's page."""
        patient_id = self._patient_id()
        if patient_id is None:
            return [_page_error("We could not identify your account.", HTTPStatus.BAD_REQUEST)]
        return [HTMLResponse(
            content=render_to_string("templates/portal.html", {
                "api_path": f"{PLUGIN_API_PATH}/portal",
                "available": not config_problems(self.secrets, OAUTH_SECRETS),
            }) or "",
            status_code=HTTPStatus.OK,
        )]

    @api.get("/static/<asset>")
    def static_asset(self) -> list[Response | Effect]:
        """Serve the page's own CSS or JS. Carries no patient data."""
        name = self.request.path_params["asset"]
        content_type = PORTAL_ASSETS.get(name)
        if content_type is None:
            return [Response(status_code=HTTPStatus.NOT_FOUND)]
        return [Response(
            (render_to_string(f"static/{name}") or "").encode(),
            status_code=HTTPStatus.OK,
            headers={"Cache-Control": "no-cache"},
            content_type=content_type,
        )]

    @api.get("/status")
    def status(self) -> list[Response | Effect]:
        """Whether the patient is connected, and since when."""
        patient_id = self._patient_id()
        if patient_id is None:
            return [JSONResponse(content={"error": "invalid_patient"}, status_code=HTTPStatus.BAD_REQUEST)]
        status, _ = connection_status(patient_id, _now())
        tokens = get_tokens(patient_id)
        if status == STATUS_CONNECTED:
            portal_status = "connected"
        elif status == STATUS_EXPIRED:
            portal_status = "reconnect"
        else:
            portal_status = "not_connected"
        return [JSONResponse(content={
            "status": portal_status,
            "connected_at": tokens.connected_at.isoformat() if tokens and tokens.connected_at else None,
        })]

    @api.get("/start")
    def start(self) -> list[Response | Effect]:
        """Send the patient to Oura's consent page.

        Opened as a top-level page rather than inside the portal frame, since
        Oura's sign-in does not run inside another site's frame.
        """
        patient_id = self._patient_id()
        if patient_id is None:
            return [_page_error("We could not identify your account.", HTTPStatus.BAD_REQUEST)]
        problems = config_problems(self.secrets, OAUTH_SECRETS)
        if problems:
            log.error(f"oura portal start: plugin settings unusable: {', '.join(problems)}")
            return [_page_error("Connecting is not available right now. Please contact your "
                                "care team.", HTTPStatus.SERVICE_UNAVAILABLE)]

        now = _now()
        nonce = live_link_nonce(get_sync_state(patient_id), now)
        if nonce is None:
            nonce = magic_link.new_nonce()
            upsert_sync_state(patient_id, last_link_nonce=nonce)
        state = magic_link.sign_state(
            patient_id, nonce, self.secrets[MAGIC_LINK_SECRET], now=int(now.timestamp())
        )
        location = build_client(self.secrets).authorize_url(state)
        return [Response(status_code=HTTPStatus.FOUND, headers={"Location": location})]

    @api.post("/disconnect")
    def disconnect(self) -> list[Response | Effect]:
        """Stop sharing. Removes everything this plugin holds for the patient."""
        patient_id = self._patient_id()
        if patient_id is None:
            return [JSONResponse(content={"error": "invalid_patient"}, status_code=HTTPStatus.BAD_REQUEST)]
        revoked = stop_sharing(patient_id, self.secrets, _now())
        return [JSONResponse(content={"disconnected": True, "revoked_at_oura": revoked})]

    def _patient_id(self) -> str | None:
        """The signed-in patient, from the header Canvas sets and strips from clients."""
        return clean_patient_id(self.request.headers.get("canvas-logged-in-user-id"))


def _page_error(message: str, status: HTTPStatus) -> HTMLResponse:
    return HTMLResponse(
        content=render_to_string("templates/connection_error.html", {"message": message}) or "",
        status_code=status,
    )
