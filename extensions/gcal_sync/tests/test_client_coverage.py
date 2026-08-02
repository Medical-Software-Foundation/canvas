"""Tests for google/client.py: GoogleRateLimitError, _error_for, find_event_by_private_property,
list_all_events.
"""

from types import SimpleNamespace

import pytest

from gcal_sync.google.client import (
    GoogleApiError,
    GoogleCalendarClient,
    GoogleRateLimitError,
    _error_for,
)


def _client(mocker):
    http = mocker.patch("gcal_sync.google.client.Http").return_value
    return GoogleCalendarClient("tok"), http


def _resp(status, body=None, text="err"):
    return SimpleNamespace(status_code=status, json=lambda: (body or {}), text=text)


# --- _error_for -----------------------------------------------------------------------------------


def test_error_for_rate_limit_403_usage_limits():
    exc = _error_for(403, '{"error": {"errors": [{"domain": "usageLimits"}]}}')
    assert isinstance(exc, GoogleRateLimitError)
    assert exc.status_code == 403


def test_error_for_rate_limit_429():
    exc = _error_for(429, "rateLimitExceeded")
    assert isinstance(exc, GoogleRateLimitError)
    assert exc.status_code == 429


def test_error_for_rate_limit_user_rate():
    exc = _error_for(403, "userRateLimitExceeded")
    assert isinstance(exc, GoogleRateLimitError)


def test_error_for_quota_exceeded():
    exc = _error_for(403, "quotaExceeded")
    assert isinstance(exc, GoogleRateLimitError)


def test_error_for_daily_limit():
    exc = _error_for(429, "dailyLimitExceeded")
    assert isinstance(exc, GoogleRateLimitError)


def test_error_for_plain_403_is_not_rate_limit():
    exc = _error_for(403, "forbidden: not shared")
    assert isinstance(exc, GoogleApiError)
    assert not isinstance(exc, GoogleRateLimitError)


def test_error_for_500_is_plain_error():
    exc = _error_for(500, "server error")
    assert isinstance(exc, GoogleApiError)
    assert not isinstance(exc, GoogleRateLimitError)


# --- GoogleRateLimitError is a subclass of GoogleApiError -----------------------------------------


def test_rate_limit_error_is_api_error():
    exc = GoogleRateLimitError(429, "too many")
    assert isinstance(exc, GoogleApiError)
    assert exc.status_code == 429
    assert "429" in str(exc)


# --- find_event_by_private_property ---------------------------------------------------------------


def test_find_event_returns_first_match(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": [{"id": "g1"}]})
    result = client.find_event_by_private_property("cal@x", "canvasApptId", "appt-1")
    assert result["id"] == "g1"
    # URL should contain the privateExtendedProperty param
    url = http.get.call_args.args[0]
    assert "privateExtendedProperty" in url


def test_find_event_returns_none_when_empty(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": []})
    result = client.find_event_by_private_property("cal@x", "canvasApptId", "appt-1")
    assert result is None


def test_find_event_raises_on_error(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(500, text="server error")
    with pytest.raises(GoogleApiError):
        client.find_event_by_private_property("cal@x", "canvasApptId", "appt-1")


def test_find_event_raises_rate_limit_on_403(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(403, text="usageLimits")
    with pytest.raises(GoogleRateLimitError):
        client.find_event_by_private_property("cal@x", "canvasApptId", "appt-1")


# --- list_all_events ------------------------------------------------------------------------------


def test_list_all_events_single_page(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": [{"id": "a"}, {"id": "b"}]})
    events = client.list_all_events("cal@x", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert len(events) == 2
    assert events[0]["id"] == "a"


def test_list_all_events_follows_pagination(mocker):
    client, http = _client(mocker)
    http.get.side_effect = [
        _resp(200, {"items": [{"id": "a"}], "nextPageToken": "p2"}),
        _resp(200, {"items": [{"id": "b"}]}),
    ]
    events = client.list_all_events("cal@x", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert [e["id"] for e in events] == ["a", "b"]
    assert http.get.call_count == 2
    # Second call should carry the page token
    second_url = http.get.call_args_list[1].args[0]
    assert "pageToken=p2" in second_url


def test_list_all_events_raises_on_error(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(500, text="boom")
    with pytest.raises(GoogleApiError):
        client.list_all_events("cal@x", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")


def test_list_all_events_uses_single_events_true(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": []})
    client.list_all_events("cal@x", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    url = http.get.call_args.args[0]
    assert "singleEvents=true" in url
    assert "timeMin=" in url
    assert "timeMax=" in url


# --- list_event_deltas uses full pull time params when no sync token -----


def test_list_event_deltas_full_pull_params(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": [], "nextSyncToken": "tok"})
    events, token = client.list_event_deltas(
        "cal@x", sync_token="", time_min="2026-01-01T00:00:00Z", time_max="2027-01-01T00:00:00Z"
    )
    url = http.get.call_args.args[0]
    assert "timeMin=" in url
    assert "timeMax=" in url
    assert "syncToken" not in url
    assert token == "tok"


# --- insert_event 201 is success ---


def test_insert_event_accepts_201(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(201, {"id": "g-1"})
    result = client.insert_event("cal@x", {})
    assert result["id"] == "g-1"


# --- insert/patch/delete raise rate limit on 429 ---


def test_insert_event_raises_rate_limit_on_429(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(429, text="rateLimitExceeded")
    with pytest.raises(GoogleRateLimitError):
        client.insert_event("cal@x", {})


def test_patch_event_raises_rate_limit_on_429(mocker):
    client, http = _client(mocker)
    http.patch.return_value = _resp(429, text="rateLimitExceeded")
    with pytest.raises(GoogleRateLimitError):
        client.patch_event("cal@x", "e1", {})


def test_delete_event_raises_rate_limit_on_429(mocker):
    client, http = _client(mocker)
    http.delete.return_value = _resp(429, text="rateLimitExceeded")
    with pytest.raises(GoogleRateLimitError):
        client.delete_event("cal@x", "e1")
