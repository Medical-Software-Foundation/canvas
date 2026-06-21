"""Tests for the Google Calendar API client: URL construction, error mapping, pagination, 410."""

import pytest

from gcal_sync.google import client as client_module
from gcal_sync.google.client import GoogleApiError, GoogleCalendarClient


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeHttp:
    """Records requests and returns queued responses in order."""

    def __init__(self):
        self.requests = []
        self.responses = []

    def _next(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, headers=None):
        return self._next("GET", url, headers=headers)

    def post(self, url, json=None, data=None, headers=None):
        return self._next("POST", url, json=json, headers=headers)

    def patch(self, url, json=None, data=None, headers=None):
        return self._next("PATCH", url, json=json, headers=headers)

    def delete(self, url, headers=None):
        return self._next("DELETE", url, headers=headers)


@pytest.fixture
def fake_http(mocker):
    fake = FakeHttp()
    mocker.patch.object(client_module, "Http", return_value=fake)
    return fake


def test_insert_event_posts_to_encoded_calendar(fake_http):
    fake_http.responses = [FakeResponse(200, {"id": "g-1"})]
    client = GoogleCalendarClient("tok")
    result = client.insert_event("dr@example.com", {"summary": "x"})

    assert result["id"] == "g-1"
    method, url, kwargs = fake_http.requests[0]
    assert method == "POST"
    # Absolute URL under the Calendar API base, with the @ percent-encoded into the path.
    assert url == "https://www.googleapis.com/calendar/v3/calendars/dr%40example.com/events"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_insert_event_raises_with_status_on_error(fake_http):
    fake_http.responses = [FakeResponse(403, text="forbidden")]
    client = GoogleCalendarClient("tok")
    with pytest.raises(GoogleApiError) as exc:
        client.insert_event("dr@example.com", {})
    assert exc.value.status_code == 403


def test_delete_event_is_idempotent_on_404_and_410(fake_http):
    fake_http.responses = [FakeResponse(404), FakeResponse(410)]
    client = GoogleCalendarClient("tok")
    # Neither should raise — the event being already gone is success.
    client.delete_event("dr@example.com", "g-1")
    client.delete_event("dr@example.com", "g-2")


def test_delete_event_raises_on_server_error(fake_http):
    fake_http.responses = [FakeResponse(500, text="boom")]
    client = GoogleCalendarClient("tok")
    with pytest.raises(GoogleApiError):
        client.delete_event("dr@example.com", "g-1")


def test_get_event_returns_none_when_gone(fake_http):
    fake_http.responses = [FakeResponse(410)]
    client = GoogleCalendarClient("tok")
    assert client.get_event("dr@example.com", "g-1") is None


def test_list_event_deltas_follows_pagination(fake_http):
    fake_http.responses = [
        FakeResponse(200, {"items": [{"id": "a"}], "nextPageToken": "p2"}),
        FakeResponse(200, {"items": [{"id": "b"}], "nextSyncToken": "sync-xyz"}),
    ]
    client = GoogleCalendarClient("tok")
    events, token = client.list_event_deltas("dr@example.com", sync_token="prev")

    assert [e["id"] for e in events] == ["a", "b"]
    assert token == "sync-xyz"
    # First request carried the prior syncToken.
    assert "syncToken=prev" in fake_http.requests[0][1]
    # Second request carried the page token.
    assert "pageToken=p2" in fake_http.requests[1][1]


def test_list_event_deltas_raises_410_for_invalid_token(fake_http):
    fake_http.responses = [FakeResponse(410, text="sync token invalid")]
    client = GoogleCalendarClient("tok")
    with pytest.raises(GoogleApiError) as exc:
        client.list_event_deltas("dr@example.com", sync_token="stale")
    assert exc.value.status_code == 410


def test_watch_events_sends_channel_config(fake_http):
    fake_http.responses = [FakeResponse(200, {"resourceId": "res-1", "expiration": "123"})]
    client = GoogleCalendarClient("tok")
    result = client.watch_events("dr@example.com", "chan-1", "https://x/webhook", "tok2", 3600)

    assert result["resourceId"] == "res-1"
    _, url, kwargs = fake_http.requests[0]
    assert url.endswith("/events/watch")
    assert kwargs["json"]["id"] == "chan-1"
    assert kwargs["json"]["type"] == "web_hook"
    assert kwargs["json"]["token"] == "tok2"


def test_stop_channel_tolerates_404(fake_http):
    fake_http.responses = [FakeResponse(404)]
    client = GoogleCalendarClient("tok")
    client.stop_channel("chan-1", "res-1")  # should not raise
