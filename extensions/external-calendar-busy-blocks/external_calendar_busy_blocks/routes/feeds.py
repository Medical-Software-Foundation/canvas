import json
import re

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from external_calendar_busy_blocks.auth import canonical_staff_id
from external_calendar_busy_blocks.data.models import (
    ImportedEvent,
    StaffCalendarFeed,
)
from external_calendar_busy_blocks.http.fetcher import FetchOk, fetch_feed


class FeedsAPI(StaffSessionAuthMixin, SimpleAPI):
    """POST /feeds to connect, POST /feeds/delete to disconnect."""

    @api.post("/feeds")
    def create_feed(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]

        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=400)]

        url = (body.get("ics_url") or "").strip()
        if not self._is_https_url(url):
            return [JSONResponse({"error": "ICS URL must be HTTPS"}, status_code=400)]
        if not self._is_allowed_host(url):
            return [JSONResponse(
                {"error": "ICS URL host is not a supported calendar provider "
                          "(Google, Outlook/Office 365, or Apple iCloud)"},
                status_code=400,
            )]

        # Probe: must respond with something that starts with BEGIN:VCALENDAR
        result = fetch_feed(url, etag=None, last_modified=None)
        if not isinstance(result, FetchOk) or not result.body.lstrip().startswith(b"BEGIN:VCALENDAR"):
            return [JSONResponse(
                {"error": "URL does not return a valid iCalendar feed"},
                status_code=400,
            )]

        existing = StaffCalendarFeed.objects.filter(staff_id=staff_id).first()
        if existing:
            existing.ics_url = url
            existing.is_active = True
            existing.last_error = None
            existing.last_etag = None
            existing.last_modified = None
            existing.save()
        else:
            StaffCalendarFeed(staff_id=staff_id, ics_url=url, is_active=True).save()

        return [JSONResponse({"status": "connected"}, status_code=200)]

    @api.post("/feeds/delete")
    def delete_feed(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]

        feed = StaffCalendarFeed.objects.filter(staff_id=staff_id).first()
        if feed is None:
            return [JSONResponse({"status": "no feed"}, status_code=200)]

        effects: list[Effect] = []
        for row in ImportedEvent.objects.filter(staff_id=staff_id):
            effects.append(Event(event_id=row.canvas_event_id).delete())
            row.delete()

        feed.delete()
        return [*effects, JSONResponse({"status": "disconnected"}, status_code=200)]

    def _logged_in_staff_id(self) -> str | None:
        return canonical_staff_id(self.request.headers)

    _HTTPS_URL_REGEX = re.compile(r"^https://[^/?#\s]+", re.IGNORECASE)

    # Extract the host (authority) portion of an https URL: everything between
    # "https://" and the next "/", "?", "#", or end-of-string. Strips any
    # userinfo ("user@") and port (":443").
    _HOST_REGEX = re.compile(r"^https://(?:[^/@?#\s]*@)?([^/:?#\s]+)", re.IGNORECASE)

    # Allowlist of calendar-provider host suffixes. The SSRF mitigation: the
    # feed fetcher issues server-side GETs from Canvas's network, so an
    # unrestricted host would let an authenticated provider probe internal
    # services (169.254.169.254, 127.0.0.1, RFC1918 hosts). The plugin sandbox
    # does not allowlist `socket`/`ipaddress`, so IP-range blocking and DNS
    # resolution are unavailable; a provider-host allowlist is the robust
    # in-sandbox mitigation. v1 limitation: self-hosted ICS feeds (Nextcloud,
    # Fastmail, etc.) are not supported.
    _ALLOWED_HOST_SUFFIXES = (
        ".google.com",          # calendar.google.com
        ".calendar.google.com",
        ".outlook.com",         # outlook.office365.com, outlook.live.com
        ".outlook.office365.com",
        ".office365.com",
        ".live.com",
        ".icloud.com",          # p##-caldav.icloud.com, *.icloud.com
    )

    @staticmethod
    def _is_https_url(url: str) -> bool:
        return bool(FeedsAPI._HTTPS_URL_REGEX.match(url))

    @staticmethod
    def _is_allowed_host(url: str) -> bool:
        match = FeedsAPI._HOST_REGEX.match(url)
        if not match:
            return False
        host = match.group(1).lower().rstrip(".")
        return any(
            host == suffix.lstrip(".") or host.endswith(suffix)
            for suffix in FeedsAPI._ALLOWED_HOST_SUFFIXES
        )
