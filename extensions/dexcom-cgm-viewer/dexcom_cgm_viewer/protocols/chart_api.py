"""Staff-authenticated SimpleAPI for the chart-drawer Application.

Routes:
  GET  /                       → HTML shell (inline CSS+JS)
  GET  /data?patient_id=&range → JSON view-model
  POST /sync?patient_id=&range → manual incremental pull from Dexcom
  POST /send-link?patient_id=  → mint magic-link JWT and SMS/email it
  POST /disconnect?patient_id= → purge tokens + cached glucose data
"""

import datetime as dt
from http import HTTPStatus
from urllib.parse import quote

from pydantic import ValidationError

from canvas_sdk.effects import Effect
from canvas_sdk.effects.note.message import Message
from canvas_sdk.effects.simple_api import (
    HTMLResponse,
    JSONResponse,
    Response,
)
from canvas_sdk.handlers.simple_api import (
    SimpleAPI,
    StaffSessionAuthMixin,
    api,
)
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from logger import log

from dexcom_cgm_viewer.services.chart_data import build_payload, payload_to_dict
from dexcom_cgm_viewer.services.crypto import TokenCipher
from dexcom_cgm_viewer.services.dexcom_client import (
    DexcomAPIError,
    DexcomAuthError,
    DexcomClient,
)
from dexcom_cgm_viewer.services.email import (
    EmailDeliveryError,
    patient_email_address,
    send_magic_link_email,
)
from dexcom_cgm_viewer.services.magic_link import mint as mint_magic_link
from dexcom_cgm_viewer.services.oauth import RefreshFailed, TokensNotFound
from dexcom_cgm_viewer.services.settings import REQUIRED_SECRETS, parse_range_days
from dexcom_cgm_viewer.services.storage import (
    delete_all_for_patient,
    upsert_sync_state,
)
from dexcom_cgm_viewer.services.sync import sync_patient


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_isoformat(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


class DexcomChartAPI(StaffSessionAuthMixin, SimpleAPI):
    """All staff-only routes for the chart drawer."""

    @api.get("/")
    def shell(self) -> list[Response | Effect]:
        """Render the chart-drawer HTML shell pre-bound to ``patient_id``."""
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse(
                content={"error": "patient_id query parameter is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        return [HTMLResponse(
            content=render_to_string(
                "templates/chart.html",
                context={"patient_id": patient_id},
            ),
            status_code=HTTPStatus.OK,
        )]

    @api.get("/data")
    def get_data(self) -> list[Response | Effect]:
        """Return the view-model JSON for the current patient + range."""
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse(
                content={"error": "patient_id query parameter is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        range_days = parse_range_days(self.request.query_params.get("range"))
        # ``build_payload`` only reads local plugin tables and runs pure-Python
        # aggregation. Any exception here is a programmer bug — let it raise
        # so Sentry/monitoring sees a real stack trace (REVIEW.md §3).
        payload = build_payload(patient_id, range_days, now=_now())
        return [JSONResponse(
            content=payload_to_dict(payload),
            status_code=HTTPStatus.OK,
        )]

    @api.post("/sync")
    def sync_now(self) -> list[Response | Effect]:
        """Pull fresh egvs for the requested window and persist them."""
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse(
                content={"error": "patient_id query parameter is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        range_days = parse_range_days(self.request.query_params.get("range"))

        secrets_check = _missing_secrets(self.secrets)
        if secrets_check:
            return [JSONResponse(
                content={"error": f"missing plugin secrets: {secrets_check}"},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )]

        client = _build_client(self.secrets)
        cipher = TokenCipher()
        now = _now()
        # Only catch the expected external-service errors from Dexcom and the
        # bounded set raised by sync_patient. Programmer bugs (AttributeError,
        # KeyError, etc.) must surface to monitoring — REVIEW.md §3.
        try:
            result = sync_patient(
                patient_id=patient_id,
                range_days=range_days,
                client=client,
                cipher=cipher,
                now=now,
            )
        except TokensNotFound:
            return [JSONResponse(
                content={"error": "patient is not connected to Dexcom"},
                status_code=HTTPStatus.CONFLICT,
            )]
        except RefreshFailed as exc:
            # sync.py's _fetch_with_refresh already wrote last_error=
            # "refresh_failed" before re-raising. Do NOT overwrite it here:
            # chart_data._resolve_status keys the "expired" UI state (which
            # surfaces the "Generate connection link" / reconnect action) off
            # that exact string. Clobbering it with "sync_failed" pins the UI
            # to "connected" and hides the documented recovery path
            # (see oauth_api on-callback state reset).
            log.warning(f"Dexcom refresh failed for {patient_id}: {exc}")
            return [JSONResponse(
                content={"error": "sync failed; reconnect required"},
                status_code=HTTPStatus.BAD_GATEWAY,
            )]
        except (DexcomAuthError, DexcomAPIError) as exc:
            log.warning(f"Dexcom sync failed for {patient_id}: {exc}")
            upsert_sync_state(
                patient_id, last_error="sync_failed", last_error_at=now,
            )
            return [JSONResponse(
                content={"error": "sync failed; showing last synced data"},
                status_code=HTTPStatus.BAD_GATEWAY,
            )]

        return [JSONResponse(
            content={
                "egvs_persisted": result.egvs_persisted,
                "egvs_purged": result.egvs_purged,
                "summaries_written": result.summaries_written,
                "last_egv_system_time": _utc_isoformat(result.last_egv_system_time),
            },
            status_code=HTTPStatus.OK,
        )]

    @api.post("/send-link")
    def send_link(self) -> list[Response | Effect]:
        """Mint a magic link and deliver it over the staff-selected channels.

        The ``channels`` query parameter is a comma-separated subset of
        ``email`` and ``portal``. When omitted, both are attempted (preserves
        prior behavior). The link is always returned in the JSON response so
        the staff UI can display a copyable fallback regardless of which
        channels were selected or whether delivery succeeded.
        """
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse(
                content={"error": "patient_id query parameter is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        secrets_check = _missing_secrets(
            self.secrets, required=("DEXCOM_MAGIC_LINK_SECRET", "DEXCOM_REDIRECT_URI"),
        )
        if secrets_check:
            return [JSONResponse(
                content={"error": f"missing plugin secrets: {secrets_check}"},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )]

        channels = _parse_channels(self.request.query_params.get("channels"))

        now = _now()
        secret = self.secrets["DEXCOM_MAGIC_LINK_SECRET"]
        token, nonce = mint_magic_link(patient_id, secret, now=int(now.timestamp()))
        link = _build_connect_url(self.secrets["DEXCOM_REDIRECT_URI"], token)

        upsert_sync_state(
            patient_id,
            last_link_sent_at=now,
            last_link_nonce=nonce,
            link_pending=True,
        )

        if "email" in channels:
            email_result = _try_send_email(self.secrets, patient_id, link)
        else:
            email_result = {"status": "skipped", "address": None, "error": "not_selected"}

        sender_id = self.request.headers.get("canvas-logged-in-user-id") or ""
        if "portal" in channels:
            portal_effect, portal_result = _try_build_portal_message(
                sender_id=sender_id, patient_id=patient_id, link=link,
            )
        else:
            portal_effect, portal_result = None, {"status": "skipped", "error": "not_selected"}

        effects: list[Response | Effect] = []
        if portal_effect is not None:
            effects.append(portal_effect)
        effects.append(JSONResponse(
            content={
                "link_sent_at": now.isoformat(),
                "connection_link": link,
                "expires_in_seconds": 15 * 60,
                "email_status": email_result["status"],
                "email_to": email_result["address"],
                "email_error": email_result["error"],
                "portal_status": portal_result["status"],
                "portal_error": portal_result["error"],
            },
            status_code=HTTPStatus.OK,
        ))
        return effects

    @api.get("/diagnose")
    def diagnose(self) -> list[Response | Effect]:
        """Read-only dump of the patient's messaging-relevant state.

        Used to triage why portal-message delivery is failing. Returns the
        patient's email/sms contact points with the fields that gate
        Canvas's ``CREATE_AND_SEND_MESSAGE`` channel resolution
        (``has_consent``, ``opted_out``, ``state``, ``last_verified``).
        """
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse(
                content={"error": "patient_id query parameter is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        try:
            patient = Patient.objects.get(id=patient_id)
        except Patient.DoesNotExist:
            return [JSONResponse(
                content={"error": "patient not found"},
                status_code=HTTPStatus.NOT_FOUND,
            )]

        telecom_rows = list(
            patient.telecom.filter(system__in=("email", "sms")).order_by("rank")
        )
        contact_points = [
            {
                "system": row.system,
                "value": (row.value or "")[:80],
                "use": row.use,
                "rank": row.rank,
                "state": row.state,
                "has_consent": bool(row.has_consent),
                "opted_out": bool(row.opted_out),
                "last_verified": (
                    _last_verified_value.isoformat()
                    if isinstance(
                        (_last_verified_value := getattr(row, "last_verified", None)),
                        dt.datetime,
                    ) else None
                ),
            }
            for row in telecom_rows
        ]

        return [JSONResponse(
            content={
                "patient_id": str(patient.id),
                "first_name": patient.first_name or "",
                "messageable_channel_present": _patient_has_messageable_channel(patient_id),
                "contact_points": contact_points,
            },
            status_code=HTTPStatus.OK,
        )]

    @api.post("/disconnect")
    def disconnect(self) -> list[Response | Effect]:
        """Disconnect the patient: drop tokens and purge cached glucose data."""
        patient_id = (self.request.query_params.get("patient_id") or "").strip()
        if not patient_id:
            return [JSONResponse(
                content={"error": "patient_id query parameter is required"},
                status_code=HTTPStatus.BAD_REQUEST,
            )]
        delete_all_for_patient(patient_id)
        return [JSONResponse(content={"disconnected": True}, status_code=HTTPStatus.OK)]


def _missing_secrets(
    secrets: dict[str, str] | None,
    required: tuple[str, ...] = REQUIRED_SECRETS,
) -> str:
    """Return a comma-separated list of missing required secret keys."""
    if not secrets:
        return ", ".join(required)
    missing = [name for name in required if not secrets.get(name)]
    return ", ".join(missing)


def _parse_channels(raw: str | None) -> set:
    """Parse the comma-separated ``channels`` query parameter.

    Returns a set drawn from ``{"email", "portal"}``. When the parameter is
    absent (``None``), both channels are returned so the endpoint keeps its
    prior send-to-all behavior. An explicitly empty string yields the empty
    set — staff chose copy-link only.
    """
    if raw is None:
        return {"email", "portal"}
    selected = {token.strip().lower() for token in raw.split(",") if token.strip()}
    return selected & {"email", "portal"}


def _build_client(secrets: dict[str, str]) -> DexcomClient:
    """Construct a ``DexcomClient`` from the plugin secrets."""
    return DexcomClient(
        environment=secrets["DEXCOM_ENVIRONMENT"],
        client_id=secrets["DEXCOM_CLIENT_ID"],
        client_secret=secrets["DEXCOM_CLIENT_SECRET"],
        redirect_uri=secrets["DEXCOM_REDIRECT_URI"],
    )


def _build_connect_url(redirect_uri: str, token: str) -> str:
    """Derive the ``/connect`` URL on the same Canvas host as the redirect URI.

    Hand-parses ``scheme://host`` rather than using ``urllib.parse.urlparse``
    because the Canvas plugin sandbox only allows ``urlencode`` and ``quote``
    from ``urllib.parse``. The validation rule (no ``startswith``) is still
    honored: we split on ``://`` and only take the authority component.
    """
    if not redirect_uri:
        raise ValueError("DEXCOM_REDIRECT_URI must be an absolute URL")
    scheme, sep, rest = redirect_uri.partition("://")
    if sep != "://" or not scheme or not rest:
        raise ValueError("DEXCOM_REDIRECT_URI must be an absolute URL")
    host, _, _ = rest.partition("/")
    if not host:
        raise ValueError("DEXCOM_REDIRECT_URI is missing a host")
    return (
        f"{scheme}://{host}/plugin-io/api/dexcom_cgm_viewer/"
        f"connect?token={quote(token, safe='')}"
    )


def _try_send_email(
    secrets: dict,
    patient_id: str,
    link: str,
) -> dict:
    """Attempt to email the magic link via SendGrid.

    Returns a dict with three keys:
      * ``status``: one of ``"sent"``, ``"skipped"``, ``"failed"``
      * ``address``: the email used, or ``None``
      * ``error``: a short reason string when status is not ``"sent"``

    Catches only the expected ``EmailDeliveryError`` from the SendGrid
    transport so the copyable-link fallback still works. Programmer bugs in
    the helper itself propagate (REVIEW.md §3).
    """
    api_key = (secrets or {}).get("SENDGRID_API_KEY") or ""
    from_email = (secrets or {}).get("SENDGRID_FROM_EMAIL") or ""
    if not api_key or not from_email:
        return {"status": "skipped", "address": None, "error": "sendgrid_not_configured"}

    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        return {"status": "skipped", "address": None, "error": "patient_not_found"}

    to_email = patient_email_address(patient)
    if not to_email:
        return {"status": "skipped", "address": None, "error": "no_email_on_file"}

    first_name = (patient.first_name or "").strip() if hasattr(patient, "first_name") else ""

    try:
        send_magic_link_email(
            api_key=api_key,
            from_email=from_email,
            to_email=to_email,
            patient_first_name=first_name,
            link=link,
        )
    except EmailDeliveryError as exc:
        log.warning(f"SendGrid rejected magic-link email for {patient_id}: {exc}")
        return {"status": "failed", "address": to_email, "error": str(exc)}

    return {"status": "sent", "address": to_email, "error": None}


def _patient_has_messageable_channel(patient_id: str) -> bool:
    """Return True if the patient has at least one usable messaging channel.

    The Canvas effect interpreter raises ``Channel not supported`` for
    ``CREATE_AND_SEND_MESSAGE`` when no channel can be resolved. We pre-flight
    that check here to avoid emitting an effect we know will fail, and to
    surface a clearer reason in the response payload.
    """
    try:
        patient = Patient.objects.get(id=patient_id)
    except Patient.DoesNotExist:
        return False
    return bool(patient.telecom.filter(
        system__in=("email", "sms"),
        has_consent=True,
        opted_out=False,
        state="active",
    ).exists())


def _try_build_portal_message(
    *,
    sender_id: str,
    patient_id: str,
    link: str,
) -> tuple:
    """Construct an in-portal ``Message`` effect carrying the magic link.

    Returns ``(effect_or_None, status_dict)``. We pre-flight the patient's
    messaging channels and skip the effect entirely when no consenting,
    non-opted-out, active email/sms contact point exists — Canvas would
    raise ``Channel not supported`` downstream otherwise.
    """
    if not sender_id:
        return None, {"status": "skipped", "error": "no_staff_sender"}
    if not _patient_has_messageable_channel(patient_id):
        return None, {"status": "skipped", "error": "no_messageable_channel"}
    body = (
        "Your care team has shared a link to securely connect your Dexcom CGM "
        "to your chart. Tap the link below on your phone (expires in 15 minutes):\n\n"
        f"{link}\n\n"
        "If you didn't request this, you can safely ignore this message."
    )
    # ``Message.create_and_send`` validates sender/recipient via Pydantic and
    # raises ``ValidationError`` when either id is malformed or doesn't resolve
    # to a Patient/Staff. Any other exception is a bug and must surface.
    try:
        effect = Message(
            content=body,
            sender_id=sender_id,
            recipient_id=patient_id,
        ).create_and_send()
    except ValidationError as exc:
        log.warning(f"Failed to construct portal Message effect: {exc}")
        return None, {"status": "failed", "error": str(exc)}
    return effect, {"status": "sent", "error": None}


