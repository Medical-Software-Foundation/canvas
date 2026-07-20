"""Tests for GoogleCalendarClient HTTP methods (insert/patch/delete/get/watch/stop)."""

from types import SimpleNamespace

import pytest

from gcal_sync.google.client import GoogleApiError, GoogleCalendarClient


def _client(mocker):
    http = mocker.patch("gcal_sync.google.client.Http").return_value
    return GoogleCalendarClient("tok"), http


def _resp(status, body=None):
    return SimpleNamespace(status_code=status, json=lambda: (body or {}), text="err")


def test_insert_event_returns_created(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(200, {"id": "e1"})
    assert client.insert_event("c", {})["id"] == "e1"


def test_insert_event_raises_on_error(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(500)
    with pytest.raises(GoogleApiError):
        client.insert_event("c", {})


def test_patch_event_ok(mocker):
    client, http = _client(mocker)
    http.patch.return_value = _resp(200, {"id": "e1"})
    assert client.patch_event("c", "e1", {})["id"] == "e1"


def test_patch_event_error(mocker):
    client, http = _client(mocker)
    http.patch.return_value = _resp(404)
    with pytest.raises(GoogleApiError):
        client.patch_event("c", "e1", {})


def test_delete_event_treats_gone_as_success(mocker):
    client, http = _client(mocker)
    http.delete.return_value = _resp(410)
    client.delete_event("c", "e1")  # no raise


def test_delete_event_raises_on_unexpected(mocker):
    client, http = _client(mocker)
    http.delete.return_value = _resp(500)
    with pytest.raises(GoogleApiError):
        client.delete_event("c", "e1")


def test_get_event_returns_none_when_gone(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(404)
    assert client.get_event("c", "e1") is None


def test_get_event_returns_event(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"id": "e1"})
    assert client.get_event("c", "e1")["id"] == "e1"


def test_get_event_raises_on_error(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(500)
    with pytest.raises(GoogleApiError):
        client.get_event("c", "e1")


def test_find_event_by_private_property_returns_first_match(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": [{"id": "e1"}, {"id": "e2"}]})
    out = client.find_event_by_private_property("c", "canvasApptId", "appt-1")
    assert out["id"] == "e1"
    # filter is passed as the privateExtendedProperty query param
    url = http.get.call_args.args[0]
    assert "privateExtendedProperty=canvasApptId%3Dappt-1" in url


def test_find_event_by_private_property_returns_none_when_empty(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(200, {"items": []})
    assert client.find_event_by_private_property("c", "canvasApptId", "appt-1") is None


def test_find_event_by_private_property_raises_on_error(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(500)
    with pytest.raises(GoogleApiError):
        client.find_event_by_private_property("c", "canvasApptId", "appt-1")


def test_list_all_events_paginates(mocker):
    client, http = _client(mocker)
    http.get.side_effect = [
        _resp(200, {"items": [{"id": "a"}], "nextPageToken": "p2"}),
        _resp(200, {"items": [{"id": "b"}]}),  # no nextPageToken -> stop
    ]
    out = client.list_all_events("c", "t0", "t1")
    assert [e["id"] for e in out] == ["a", "b"]
    assert http.get.call_count == 2


def test_list_all_events_raises_on_error(mocker):
    client, http = _client(mocker)
    http.get.return_value = _resp(500)
    with pytest.raises(GoogleApiError):
        client.list_all_events("c", "t0", "t1")


def test_watch_events_returns_channel(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(200, {"resourceId": "r"})
    out = client.watch_events("c", channel_id="ch", address="https://x", token="t", ttl_seconds=60)
    assert out["resourceId"] == "r"


def test_watch_events_error(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(403)
    with pytest.raises(GoogleApiError):
        client.watch_events("c", channel_id="ch", address="https://x", token="t", ttl_seconds=60)


def test_stop_channel_ok_and_404(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(404)  # already stopped -> success
    client.stop_channel("ch", "r")


def test_stop_channel_raises_on_error(mocker):
    client, http = _client(mocker)
    http.post.return_value = _resp(500)
    with pytest.raises(GoogleApiError):
        client.stop_channel("ch", "r")
