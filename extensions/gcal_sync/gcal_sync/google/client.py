"""Thin Google Calendar API v3 client built on the Canvas SDK HTTP client.

Every call impersonates a provider via a bearer token from :class:`gcal_sync.google.auth.GoogleAuth`.
The client only knows how to talk to Google; mapping/echo/decision logic lives in the handlers.

Uses ``canvas_sdk.utils.http.Http`` (30s timeout, validation, metrics) rather than raw ``requests``
per CLAUDE.md. The SDK client is constructed WITHOUT a ``base_url`` and every call passes an absolute
URL: ``Http(base_url=...)`` rejects leading-slash relative paths because ``urljoin`` strips the base
path (``You may not access other URLs using this client.``). Errors raise :class:`GoogleApiError`
carrying the HTTP status so callers can special-case ``410 Gone`` without parsing strings.
"""

from urllib.parse import quote, urlencode

from canvas_sdk.utils.http import Http

API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleApiError(RuntimeError):
    """A non-success response from the Google Calendar API."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"Google Calendar API {status_code}: {message}")
        self.status_code = status_code


class GoogleCalendarClient:
    """Calendar-event CRUD, watch-channel, and incremental-list operations for one access token."""

    def __init__(self, access_token: str) -> None:
        # No base_url: the SDK client only allows URLs under its base_url, and a base_url with
        # leading-slash paths fails join validation. We pass absolute URLs built from API_BASE.
        self._http = Http()
        self._headers = {"Authorization": f"Bearer {access_token}"}

    @staticmethod
    def _url(path: str) -> str:
        return f"{API_BASE}{path}"

    @staticmethod
    def _cal(calendar_id: str) -> str:
        # Calendar ids are email addresses; the path segment must be percent-encoded.
        return quote(calendar_id, safe="")

    def insert_event(self, calendar_id: str, body: dict) -> dict:
        """Create an event; returns the created Google event (including its ``id``)."""
        resp = self._http.post(
            self._url(f"/calendars/{self._cal(calendar_id)}/events"), json=body, headers=self._headers
        )
        if resp.status_code not in (200, 201):
            raise GoogleApiError(resp.status_code, resp.text)
        created: dict = resp.json()
        return created

    def patch_event(self, calendar_id: str, event_id: str, body: dict) -> dict:
        """Update an existing event in place."""
        resp = self._http.patch(
            self._url(f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id, safe='')}"),
            json=body,
            headers=self._headers,
        )
        if resp.status_code != 200:
            raise GoogleApiError(resp.status_code, resp.text)
        patched: dict = resp.json()
        return patched

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete an event. A ``404``/``410`` (already gone) is treated as success — idempotent."""
        resp = self._http.delete(
            self._url(f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id, safe='')}"),
            headers=self._headers,
        )
        if resp.status_code not in (200, 204, 404, 410):
            raise GoogleApiError(resp.status_code, resp.text)

    def get_event(self, calendar_id: str, event_id: str) -> dict | None:
        """Fetch a single event, or ``None`` if it no longer exists."""
        resp = self._http.get(
            self._url(f"/calendars/{self._cal(calendar_id)}/events/{quote(event_id, safe='')}"),
            headers=self._headers,
        )
        if resp.status_code in (404, 410):
            return None
        if resp.status_code != 200:
            raise GoogleApiError(resp.status_code, resp.text)
        event: dict = resp.json()
        return event

    def find_event_by_private_property(
        self, calendar_id: str, key: str, value: str
    ) -> dict | None:
        """Return the first LIVE event whose private extended property ``key`` equals ``value``.

        Lets an outbound push ADOPT an event it created earlier (matched by ``canvasApptId``) when the
        local mapping is missing, instead of inserting a duplicate. ``showDeleted`` is left false so a
        deleted/cancelled remnant is never adopted — a truly gone event falls through to a fresh insert.
        """
        params = {"privateExtendedProperty": f"{key}={value}", "maxResults": "1"}
        url = self._url(f"/calendars/{self._cal(calendar_id)}/events?{urlencode(params)}")
        resp = self._http.get(url, headers=self._headers)
        if resp.status_code != 200:
            raise GoogleApiError(resp.status_code, resp.text)
        items = resp.json().get("items", [])
        return items[0] if items else None

    def list_event_deltas(
        self, calendar_id: str, sync_token: str = "", time_min: str = "", time_max: str = ""
    ) -> tuple[list[dict], str]:
        """Pull changed events, following pagination.

        With a ``sync_token`` this is an incremental pull (only what changed since); without one it
        is a full pull bounded by ``time_min``/``time_max``. The ``time_max`` bound is essential:
        with ``singleEvents=true`` an unbounded recurring event expands into one instance per
        occurrence indefinitely (we once imported a daily event out to 2040). Returns
        ``(events, next_sync_token)``. Raises ``GoogleApiError(410)`` on an invalid sync token.
        """
        events: list[dict] = []
        page_token = ""
        next_sync_token = ""

        while True:
            params: dict[str, str] = {"showDeleted": "true", "singleEvents": "true"}
            if sync_token:
                params["syncToken"] = sync_token
            else:
                if time_min:
                    params["timeMin"] = time_min
                if time_max:
                    params["timeMax"] = time_max
            if page_token:
                params["pageToken"] = page_token

            url = self._url(f"/calendars/{self._cal(calendar_id)}/events?{urlencode(params)}")
            resp = self._http.get(url, headers=self._headers)
            if resp.status_code != 200:
                raise GoogleApiError(resp.status_code, resp.text)

            payload = resp.json()
            events.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken", "")
            if not page_token:
                next_sync_token = payload.get("nextSyncToken", "")
                break

        return events, next_sync_token

    def list_all_events(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
        """Return all LIVE events on the calendar in ``[time_min, time_max]`` (paginated).

        Used by the reconcile sweep to find events we pushed whose Canvas appointment is gone/terminal
        (orphans to delete) or duplicated (extras to collapse). ``showDeleted`` is omitted so
        already-deleted events aren't re-processed; ``singleEvents`` expands recurrences.
        """
        events: list[dict] = []
        page_token = ""
        while True:
            params: dict[str, str] = {
                "singleEvents": "true",
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": "250",
            }
            if page_token:
                params["pageToken"] = page_token
            url = self._url(f"/calendars/{self._cal(calendar_id)}/events?{urlencode(params)}")
            resp = self._http.get(url, headers=self._headers)
            if resp.status_code != 200:
                raise GoogleApiError(resp.status_code, resp.text)
            payload = resp.json()
            events.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken", "")
            if not page_token:
                break
        return events

    def watch_events(
        self, calendar_id: str, channel_id: str, address: str, token: str, ttl_seconds: int
    ) -> dict:
        """Open an ``events.watch`` push channel. Returns Google's channel resource (``resourceId``)."""
        body = {
            "id": channel_id,
            "type": "web_hook",
            "address": address,
            "token": token,
            "params": {"ttl": str(ttl_seconds)},
        }
        resp = self._http.post(
            self._url(f"/calendars/{self._cal(calendar_id)}/events/watch"),
            json=body,
            headers=self._headers,
        )
        if resp.status_code != 200:
            raise GoogleApiError(resp.status_code, resp.text)
        channel: dict = resp.json()
        return channel

    def stop_channel(self, channel_id: str, resource_id: str) -> None:
        """Stop a watch channel. A ``404`` (already stopped/expired) is treated as success."""
        resp = self._http.post(
            self._url("/channels/stop"),
            json={"id": channel_id, "resourceId": resource_id},
            headers=self._headers,
        )
        if resp.status_code not in (200, 204, 404):
            raise GoogleApiError(resp.status_code, resp.text)
