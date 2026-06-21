"""Receives Google Calendar ``events.watch`` push notifications and pulls the delta.

Google posts a content-less ping to this endpoint whenever a watched calendar changes. The ping is
authenticated by the ``X-Goog-Channel-Token`` we set when opening the channel; it is validated
**fail-closed** (a missing secret or mismatched token is rejected, never allowed through — CLAUDE.md).

The endpoint resolves the channel to a calendar, then hands off to :class:`gcal_sync.inbound.InboundSync`
for the actual delta pull and conflict handling.
"""

from hmac import compare_digest
from http import HTTPStatus
from typing import Any

from requests import RequestException

from canvas_sdk.effects import Effect
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import Credentials, SimpleAPI, api
from logger import log

from gcal_sync.google.client import GoogleApiError
from gcal_sync.inbound import InboundSync
from gcal_sync.models import WatchChannel

# Google's header for the per-channel verification token (looked up case-insensitively).
_CHANNEL_TOKEN_HEADER = "x-goog-channel-token"
_CHANNEL_ID_HEADER = "x-goog-channel-id"
_RESOURCE_STATE_HEADER = "x-goog-resource-state"


def _header(headers: Any, name: str) -> str:
    """Case-insensitive header lookup that tolerates dict-like request headers."""
    try:
        items = headers.items()
    except AttributeError:
        return ""
    target = name.lower()
    for key, value in items:
        if str(key).lower() == target:
            return str(value)
    return ""


class GoogleWebhook(SimpleAPI):
    """Public endpoint Google pings on watched-calendar changes."""

    def authenticate(self, credentials: Credentials) -> bool:
        """Authenticate the ping by its channel token. Fails closed when the secret is unset."""
        expected = (self.secrets.get("GOOGLE_CALENDAR_WEBHOOK_TOKEN") or "").strip()
        if not expected:
            log.warning("GOOGLE_CALENDAR_WEBHOOK_TOKEN is not configured; rejecting webhook")
            return False
        provided = _header(self.request.headers, _CHANNEL_TOKEN_HEADER).strip()
        # Constant-time compare to avoid leaking the token via timing.
        return bool(provided) and compare_digest(provided, expected)

    @api.post("/google/webhook")
    def receive(self) -> list[Response | Effect]:
        resource_state = _header(self.request.headers, _RESOURCE_STATE_HEADER)
        if resource_state == "sync":
            # Initial handshake Google sends right after a channel opens — nothing changed yet.
            return [JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]

        channel_id = _header(self.request.headers, _CHANNEL_ID_HEADER)
        channel = WatchChannel.objects.filter(channel_id=channel_id).first()
        if channel is None:
            # Unknown/expired channel — acknowledge so Google stops retrying this stale channel.
            log.info("Webhook ping for unknown channel %s; acknowledging", channel_id)
            return [JSONResponse({"status": "ignored"}, status_code=HTTPStatus.OK)]

        inbound = InboundSync(self.secrets)
        try:
            stats, effects = inbound.process_calendar(channel.google_calendar_id)
        except (GoogleApiError, RequestException) as exc:
            # Transient Google/network failure: 503 asks Google to retry with backoff.
            log.error("Webhook delta pull failed for %s: %s", channel.google_calendar_id, exc)
            return [JSONResponse({"error": "delta pull failed"}, status_code=HTTPStatus.SERVICE_UNAVAILABLE)]

        log.info("Webhook delta for %s: %s", channel.google_calendar_id, stats)
        # Hold create/update/delete effects (Google -> Canvas) are applied alongside the 200 ack.
        return [*effects, JSONResponse({"status": "ok"}, status_code=HTTPStatus.OK)]
