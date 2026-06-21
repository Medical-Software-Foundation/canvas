"""Watch-channel lifecycle: open, renew, and stop Google ``events.watch`` channels (spec §6.4).

A channel tells Google to POST a ping to our webhook whenever a calendar changes. Channels expire in
≤7 days, so they must be renewed before expiry or Google→Canvas silently stops. Shared by the admin
app (open a channel when a provider is enrolled) and ``ChannelRenewalCron`` (keep them alive).
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

import arrow

from logger import log

from gcal_sync.google.auth import GoogleAuth
from gcal_sync.google.client import GoogleCalendarClient
from gcal_sync.models import WatchChannel
from gcal_sync.sync_service import ClientFactory

# Path the webhook route is mounted at: /plugin-io/api/<plugin>/<route>.
WEBHOOK_PATH = "/plugin-io/api/gcal_sync/google/webhook"
# Request the maximum useful channel lifetime; Google may cap it and returns the real expiration.
_CHANNEL_TTL_SECONDS = 7 * 24 * 60 * 60
# Renew when a channel is within this window of expiring.
RENEW_WITHIN_SECONDS = 48 * 60 * 60


class ChannelConfigError(RuntimeError):
    """Raised when required webhook configuration (base URL / token) is missing — fail closed."""


def webhook_address(secrets: dict) -> str:
    """Build the public URL Google should ping, from ``GOOGLE_WEBHOOK_BASE_URL``."""
    base = (secrets.get("GOOGLE_WEBHOOK_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise ChannelConfigError("GOOGLE_WEBHOOK_BASE_URL is not configured")
    return f"{base}{WEBHOOK_PATH}"


class ChannelManager:
    """Opens, renews, and stops watch channels for calendars."""

    def __init__(
        self, secrets: dict, client_factory: ClientFactory | None = None
    ) -> None:
        self._secrets = secrets
        self._token = (secrets.get("GOOGLE_CALENDAR_WEBHOOK_TOKEN") or "").strip()
        if not self._token:
            raise ChannelConfigError("GOOGLE_CALENDAR_WEBHOOK_TOKEN is not configured")
        self._address = webhook_address(secrets)
        auth = GoogleAuth(secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
        self._client_factory = client_factory or (
            lambda calendar_id: GoogleCalendarClient(auth.get_access_token(calendar_id))
        )

    def open_channel(self, calendar_id: str) -> WatchChannel:
        """Stop any existing channel for the calendar and open a fresh one."""
        client = self._client_factory(calendar_id)
        self._stop_existing(calendar_id, client)

        channel_id = uuid4().hex
        result = client.watch_events(
            calendar_id,
            channel_id=channel_id,
            address=self._address,
            token=self._token,
            ttl_seconds=_CHANNEL_TTL_SECONDS,
        )
        channel: WatchChannel = WatchChannel.objects.create(
            google_calendar_id=calendar_id,
            channel_id=channel_id,
            resource_id=result.get("resourceId", ""),
            expiration=self._parse_expiration(result.get("expiration")),
        )
        return channel

    def renew_if_needed(self, calendar_id: str) -> bool:
        """Open/renew the channel if there is none or it expires soon. Returns whether it renewed."""
        existing = (
            WatchChannel.objects.filter(google_calendar_id=calendar_id).order_by("-created_at").first()
        )
        if existing is not None and not self._expiring_soon(existing):
            return False
        self.open_channel(calendar_id)
        return True

    def _stop_existing(self, calendar_id: str, client: GoogleCalendarClient) -> None:
        for channel in WatchChannel.objects.filter(google_calendar_id=calendar_id):
            if channel.resource_id:
                client.stop_channel(channel.channel_id, channel.resource_id)
            channel.delete()

    @staticmethod
    def _expiring_soon(channel: WatchChannel) -> bool:
        if channel.expiration is None:
            return True
        return arrow.get(channel.expiration) <= arrow.utcnow().shift(seconds=RENEW_WITHIN_SECONDS)

    @staticmethod
    def _parse_expiration(raw: Any) -> datetime | None:
        # Google returns ``expiration`` as a string of milliseconds since the epoch.
        if not raw:
            return None
        try:
            return arrow.get(int(str(raw)) / 1000).datetime
        except (ValueError, TypeError):
            log.warning("Could not parse watch channel expiration %r", raw)
            return None
