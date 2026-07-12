import json
import re

from canvas_sdk.effects import Effect
from canvas_sdk.effects.calendar import Event
from canvas_sdk.effects.simple_api import JSONResponse, Response
from canvas_sdk.handlers.simple_api import SimpleAPI, StaffSessionAuthMixin, api

from external_calendar_busy_blocks.auth import canonical_staff_id, canonicalize_staff_id, is_admin
from external_calendar_busy_blocks.calendars.admin_lookup import get_admin_calendar_id
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
        # Reject internal whitespace before host extraction. A real ICS URL
        # never contains raw whitespace (it would be percent-encoded). The host
        # regex terminates the authority at whitespace, but requests/urllib3
        # percent-encode it and keep parsing — so a tab/space/newline lets the
        # allowlist read one host while the client dials another (SSRF).
        if re.search(r"\s", url):
            return [JSONResponse(
                {"error": "ICS URL must not contain whitespace"},
                status_code=400,
            )]
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

        target_id = self._resolve_target_staff_id(staff_id, body)

        # Provision the target's Admin calendar first. An empty id means the
        # staff (or their name) could not be resolved — fail before writing a
        # feed row that would have no calendar to land busy blocks on.
        cal_id, cal_effects = get_admin_calendar_id(target_id)
        if not cal_id:
            return [JSONResponse(
                {"error": "Could not resolve the provider's calendar"},
                status_code=400,
            )]

        existing = StaffCalendarFeed.objects.filter(staff_id=target_id).first()
        if existing:
            existing.ics_url = url
            existing.is_active = True
            existing.last_error = None
            existing.last_etag = None
            existing.last_modified = None
            existing.save()
        else:
            StaffCalendarFeed(staff_id=target_id, ics_url=url, is_active=True).save()

        return [*cal_effects, JSONResponse({"status": "connected"}, status_code=200)]

    @api.post("/feeds/delete")
    def delete_feed(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]

        try:
            body = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError:
            return [JSONResponse({"error": "Invalid JSON"}, status_code=400)]

        target_id = self._resolve_target_staff_id(staff_id, body)

        feed = StaffCalendarFeed.objects.filter(staff_id=target_id).first()
        if feed is None:
            return [JSONResponse({"status": "no feed"}, status_code=200)]

        effects: list[Effect] = []
        for row in ImportedEvent.objects.filter(staff_id=target_id):
            effects.append(Event(event_id=row.canvas_event_id).delete())
            row.delete()

        feed.delete()
        return [*effects, JSONResponse({"status": "disconnected"}, status_code=200)]

    @api.get("/feeds/status")
    def feed_status(self) -> list[Response | Effect]:
        staff_id = self._logged_in_staff_id()
        if not staff_id:
            return [JSONResponse({"error": "Not authenticated"}, status_code=401)]
        if not is_admin(staff_id, self.secrets):
            return [JSONResponse({"error": "Forbidden"}, status_code=403)]

        target_id = canonicalize_staff_id(self.request.query_params.get("staff_id") or "")
        if not target_id:
            return [JSONResponse({"error": "Missing staff_id"}, status_code=400)]

        feed = StaffCalendarFeed.objects.filter(staff_id=target_id).first()
        if feed is None:
            return [JSONResponse({"connected": False}, status_code=200)]
        # Never return ics_url — it is a bearer token.
        return [JSONResponse(
            {
                "connected": bool(feed.is_active),
                "last_sync_at": str(feed.last_sync_at) if feed.last_sync_at else None,
                "last_error": feed.last_error,
            },
            status_code=200,
        )]

    def _logged_in_staff_id(self) -> str | None:
        return canonical_staff_id(self.request.headers)

    def _resolve_target_staff_id(self, logged_in: str, body: dict) -> str:
        """Return the staff id to act on.

        An admin may target another provider by sending ``staff_id`` in the
        body; the id is canonicalized to the dashless form used for Staff.id.
        For everyone else (and when no staff_id is sent), the logged-in staff is
        authoritative — a non-admin's body staff_id is ignored, so it can never
        escalate privilege.
        """
        requested = (body.get("staff_id") or "").strip()
        if requested and is_admin(logged_in, self.secrets):
            return canonicalize_staff_id(requested)
        return logged_in

    _HTTPS_URL_REGEX = re.compile(r"^https://[^/?#\s]+", re.IGNORECASE)

    # The authority is everything between "https://" and the next "/", "?", or
    # "#". Host extraction below must then split it the same way requests/
    # urllib3 do (userinfo ends at the LAST "@"); see _extract_host.
    _AUTHORITY_REGEX = re.compile(r"^https://([^/?#\s]*)", re.IGNORECASE)

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
    def _extract_host(url: str) -> str | None:
        """Return the host the HTTP client will actually connect to, or None.

        Mirrors RFC 3986 / requests/urllib3: within the authority, userinfo
        ends at the LAST "@", and the host precedes the port. The sandbox does
        not allowlist urllib.parse.urlsplit, so this is done with re + string
        ops — but it must agree with what the client dials, otherwise a
        `user@allowed.com@169.254.169.254` URL passes the allowlist while the
        client connects to the trailing internal host.
        """
        match = FeedsAPI._AUTHORITY_REGEX.match(url)
        if not match:
            return None
        authority = match.group(1)
        if "@" in authority:
            authority = authority.rsplit("@", 1)[1]  # host follows the last "@"
        if authority.startswith("["):  # IPv6 literal, e.g. [::1]:443
            end = authority.find("]")
            host = authority[1:end] if end != -1 else authority
        else:
            host = authority.split(":", 1)[0]  # strip port
        return host.lower().rstrip(".") or None

    @staticmethod
    def _is_allowed_host(url: str) -> bool:
        host = FeedsAPI._extract_host(url)
        if not host:
            return False
        return any(
            host == suffix.lstrip(".") or host.endswith(suffix)
            for suffix in FeedsAPI._ALLOWED_HOST_SUFFIXES
        )
