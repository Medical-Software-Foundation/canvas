"""Staff-authenticated SimpleAPI for the chart-drawer Application.

Routes:
  GET  /                       -> HTML shell
  GET  /static/<asset>         -> the shell's own CSS and JS, no patient data
  GET  /data?patient_id=&range -> JSON view-model, fetched live from Oura, never stored
  GET  /status?patient_id=     -> connection status only; never calls Oura
  POST /send-link?patient_id=  -> issue a connection link, optionally via the portal;
                                  ``reuse=1`` re-sends the link already out
  POST /disconnect?patient_id= -> remove the patient's tokens and connection status

Every route requires a Canvas staff session (``StaffSessionAuthMixin``), and
then passes ``_gate`` before touching patient data. The gate rejects a
``patient_id`` that is not a plausible Canvas key, refuses to run with an
unrecognized access rule, identifies the calling staff member from the
Canvas-set session headers, and checks that member against the practice's
``OURA_ACCESS_RULE`` (see ``services/access.py``). The staff session alone is
not enough: per the Canvas docs it "makes no assertions about the particular
staff member". No route ever returns token material.
"""

import datetime as dt
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.message import Message
from canvas_sdk.effects.simple_api import HTMLResponse, JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from canvas_sdk.v1.data.common import ContactPointState, ContactPointSystem
from logger import log
from pydantic import ValidationError

from oura_ring_viewer.services import magic_link
from oura_ring_viewer.services.access import (
    ACCESS_RULE,
    RULES,
    logged_in_staff_id,
    resolve_rule,
    staff_can_view,
)
from oura_ring_viewer.services.assets import CHART_ASSETS
from oura_ring_viewer.services.chart_data import (
    STATUS_CONNECTED,
    build_payload,
    connection_status,
    window,
)
from oura_ring_viewer.services.config import (
    FETCH_SECRETS,
    LINK_SECRETS,
    MAGIC_LINK_SECRET,
    REDIRECT_URI,
    build_client,
    clean_patient_id,
    config_problems,
    connect_url,
    is_sandbox,
)
from oura_ring_viewer.services.crypto import TokenCipher
from oura_ring_viewer.services.disconnect import stop_sharing
from oura_ring_viewer.services.fetch import fetch_window
from oura_ring_viewer.services.links import live_link_nonce
from oura_ring_viewer.services.oauth import RefreshFailed, TokensNotFound
from oura_ring_viewer.services.oura_client import OuraAPIError, OuraAuthError
from oura_ring_viewer.services.settings import (
    MAGIC_LINK_TTL_SECONDS,
    PLUGIN_API_PATH,
    parse_range_days,
)
from oura_ring_viewer.services.storage import get_sync_state, upsert_sync_state
from oura_ring_viewer.services.time_utils import local_today


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass(frozen=True)
class _Grant:
    """A request that passed the gate: who is asking about whom."""

    patient_id: str
    staff_id: str


def _gate(request: Any, secrets: dict[str, str] | None, *, html: bool = False) -> _Grant | Response:
    """Validate the patient id and the caller's access, in that order.

    Returns a grant, or the response to send instead. ``html`` selects a
    readable page rather than JSON, for the route the chart drawer opens.
    """
    patient_id = clean_patient_id(request.query_params.get("patient_id"))
    if patient_id is None:
        return _deny("invalid_patient_id", HTTPStatus.BAD_REQUEST, html,
                     "This chart could not identify the patient.")

    rule = resolve_rule(secrets)
    if rule is None:
        setting = f"{ACCESS_RULE} (must be one of: {', '.join(RULES)})"
        if html:
            return _staff_page(f"This plugin has an invalid setting: {setting}.",
                               HTTPStatus.SERVICE_UNAVAILABLE)
        return _misconfigured([setting])

    staff_id = logged_in_staff_id(request.headers)
    if staff_id is None:
        return _deny("not_staff", HTTPStatus.FORBIDDEN, html,
                     "Oura data is only available to signed-in staff.")

    if not staff_can_view(staff_id, patient_id, rule):
        log.info(f"oura access denied: staff {staff_id}, patient {patient_id}, rule {rule}")
        return _deny("forbidden", HTTPStatus.FORBIDDEN, html,
                     "You do not have access to this patient's Oura data.")

    return _Grant(patient_id=patient_id, staff_id=staff_id)


class OuraChartAPI(StaffSessionAuthMixin, SimpleAPI):
    """Staff-facing chart API. All routes require a Canvas staff session."""

    @api.get("/")
    def chart_shell(self) -> list[Response | Effect]:
        """Serve the chart HTML shell bound to the active patient."""
        grant = _gate(self.request, self.secrets, html=True)
        if isinstance(grant, Response):
            return [grant]
        html = render_to_string(
            "templates/chart.html",
            context={"patient_id": grant.patient_id, "api_path": PLUGIN_API_PATH},
        )
        return [HTMLResponse(content=html or "", status_code=HTTPStatus.OK)]

    @api.get("/static/<asset>")
    def static_asset(self) -> list[Response | Effect]:
        """Serve the shell's own CSS or JS. Carries no patient data."""
        name = self.request.path_params["asset"]
        content_type = CHART_ASSETS.get(name)
        if content_type is None:
            return [Response(status_code=HTTPStatus.NOT_FOUND)]
        return [Response(
            (render_to_string(f"static/{name}") or "").encode(),
            status_code=HTTPStatus.OK,
            headers={"Cache-Control": "no-cache"},
            content_type=content_type,
        )]

    @api.get("/data")
    def chart_data(self) -> list[Response | Effect]:
        """Fetch the requested window live from Oura and return the view-model.

        Nothing fetched is stored. A patient who is not connected, or whose
        connection has expired, gets their status and no data. A failed fetch
        still returns the view-model, with ``fetch_error`` set for the chart.
        """
        grant = _gate(self.request, self.secrets)
        if isinstance(grant, Response):
            return [grant]
        patient_id = grant.patient_id
        range_days = parse_range_days(self.request.query_params.get("range"))
        now = _now()
        today = local_today(now, self.environment)
        sandbox = is_sandbox(self.secrets)
        status, state = connection_status(patient_id, now)
        if status != STATUS_CONNECTED:
            return [JSONResponse(content=build_payload(
                range_days=range_days, today=today, status=status, state=state, sandbox=sandbox,
            ))]

        problems = config_problems(self.secrets, FETCH_SECRETS)
        if problems:
            return [_misconfigured(problems)]

        start_day, end_day = window(range_days, today)
        result = None
        fetch_error = ""
        try:
            result = fetch_window(
                patient_id=patient_id,
                start_day=start_day,
                end_day=end_day,
                client=build_client(self.secrets),
                cipher=TokenCipher(),
                now=now,
            )
        except TokensNotFound:
            pass  # Disconnected between the status check and the fetch.
        except (RefreshFailed, OuraAuthError) as exc:
            # fetch_window has recorded the error code the chart uses to offer a
            # reconnect; the status re-read below picks it up.
            log.warning(f"oura fetch for {patient_id} needs reconnect: {type(exc).__name__}")
            fetch_error = "reconnect_required"
        except OuraAPIError as exc:
            log.warning(f"oura fetch for {patient_id} failed with HTTP {exc.status_code}")
            too_many = exc.status_code == HTTPStatus.TOO_MANY_REQUESTS
            fetch_error = "rate_limited" if too_many else "oura_unavailable"

        status, state = connection_status(patient_id, now)
        return [JSONResponse(content=build_payload(
            range_days=range_days,
            today=today,
            status=status,
            state=state,
            rows=result.rows if result else (),
            forbidden_endpoints=result.forbidden_endpoints if result else (),
            fetch_error=fetch_error,
            sandbox=sandbox,
        ))]

    @api.get("/status")
    def status(self) -> list[Response | Effect]:
        """Connection status only, cheap enough for an open chart to check often.

        Lets a panel showing data notice that the patient stopped sharing and
        clear it, without reading Oura again.
        """
        grant = _gate(self.request, self.secrets)
        if isinstance(grant, Response):
            return [grant]
        status, _ = connection_status(grant.patient_id, _now())
        return [JSONResponse(content={"connection_status": status})]

    @api.post("/send-link")
    def send_link(self) -> list[Response | Effect]:
        """Mint a connection link and optionally deliver it via the patient portal.

        ``channels`` is ``portal`` (the default) or empty for copy-link only.
        The link is always returned so staff can share it another way if
        portal delivery is unavailable.

        With ``reuse=1`` the link that is already out is re-signed with its
        original send time, so copying or resending it does not cancel what
        the patient may already have. Without a usable link to reuse, a new
        one is issued, which cancels any earlier link.
        """
        grant = _gate(self.request, self.secrets)
        if isinstance(grant, Response):
            return [grant]
        patient_id = grant.patient_id
        problems = config_problems(self.secrets, LINK_SECRETS)
        if problems:
            return [_misconfigured(problems)]

        now = _now()
        state = get_sync_state(patient_id)
        reuse = self.request.query_params.get("reuse") == "1"
        nonce = live_link_nonce(state, now) if reuse else None
        if nonce is not None and state is not None and state.last_link_sent_at is not None:
            sent_at = state.last_link_sent_at
        else:
            nonce, sent_at = magic_link.new_nonce(), now
            # Storing the nonce invalidates any earlier link for this patient.
            upsert_sync_state(patient_id, last_link_sent_at=now, last_link_nonce=nonce, link_pending=True)
        token = magic_link.mint_link(
            patient_id, nonce, self.secrets[MAGIC_LINK_SECRET], now=int(sent_at.timestamp())
        )
        link = connect_url(self.secrets[REDIRECT_URI], token)
        expires_in = int(sent_at.timestamp()) + MAGIC_LINK_TTL_SECONDS - int(now.timestamp())

        effects: list[Response | Effect] = []
        portal_status = "skipped"
        portal_error: str | None = "not_selected"
        if "portal" in _channels(self.request.query_params.get("channels")):
            effect, portal_status, portal_error = _portal_message(
                sender_id=grant.staff_id,
                patient_id=patient_id,
                link=link,
            )
            if effect is not None:
                effects.append(effect)

        effects.append(JSONResponse(content={
            "connection_link": link,
            "link_sent_at": sent_at.isoformat(),
            "expires_in_seconds": expires_in,
            "reused": sent_at != now,
            "portal_status": portal_status,
            "portal_error": portal_error,
        }))
        return effects

    @api.post("/disconnect")
    def disconnect(self) -> list[Response | Effect]:
        """End access at Oura and remove the patient's tokens and status."""
        grant = _gate(self.request, self.secrets)
        if isinstance(grant, Response):
            return [grant]
        revoked = stop_sharing(grant.patient_id, self.secrets, _now())
        return [JSONResponse(content={"disconnected": True, "revoked_at_oura": revoked})]


def _channels(raw: str | None) -> set[str]:
    """Absent means portal; an explicit empty value means copy-link only."""
    if raw is None:
        return {"portal"}
    return {part.strip().lower() for part in raw.split(",") if part.strip()} & {"portal"}


def _portal_message(
    *, sender_id: str, patient_id: str, link: str
) -> tuple[Effect | None, str, str | None]:
    """Build the portal ``Message`` effect, or explain why it was skipped.

    Canvas fails a message with "Channel not supported" when the patient has no
    consenting, active contact point, so that is checked first rather than
    emitting an effect known to fail.
    """
    if not _has_messageable_channel(patient_id):
        return None, "skipped", "no_messageable_channel"
    body = (
        "Your care team has shared a secure link to connect your Oura Ring to your "
        "health record. Open it on your phone within 3 days:\n\n"
        f"{link}\n\n"
        "Your care team will see your sleep, readiness, activity and blood oxygen "
        "summaries. You can also connect, or stop sharing, any time from Oura Ring "
        "in your patient portal menu. If you did not expect this message, you can "
        "ignore it."
    )
    try:
        effect = Message(content=body, sender_id=sender_id, recipient_id=patient_id).create_and_send()
    except ValidationError as exc:
        log.warning(f"portal message for {patient_id} not built: {exc.error_count()} validation error(s)")
        return None, "failed", "invalid_sender_or_recipient"
    return effect, "sent", None


def _has_messageable_channel(patient_id: str) -> bool:
    patient = Patient.objects.filter(id=patient_id).first()
    if patient is None:
        return False
    return bool(
        patient.telecom.filter(
            system__in=(ContactPointSystem.EMAIL.value, ContactPointSystem.PHONE.value),
            has_consent=True,
            opted_out=False,
            state=ContactPointState.ACTIVE.value,
        ).exists()
    )


def _deny(code: str, status: HTTPStatus, html: bool, message: str) -> Response:
    """A refusal: a readable page for the chart drawer, JSON for the API routes."""
    if html:
        return _staff_page(message, status)
    return JSONResponse(content={"error": code}, status_code=status)


def _staff_page(message: str, status: HTTPStatus) -> HTMLResponse:
    html = render_to_string("templates/staff_message.html", context={"message": message, "api_path": PLUGIN_API_PATH})
    return HTMLResponse(content=html or "", status_code=status)


def _misconfigured(problems: list[str]) -> JSONResponse:
    return JSONResponse(
        content={"error": "plugin_not_configured", "settings": problems},
        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
    )
