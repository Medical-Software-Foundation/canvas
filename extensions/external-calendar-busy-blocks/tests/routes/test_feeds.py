import json
from unittest.mock import MagicMock, patch

import pytest

from external_calendar_busy_blocks.routes.feeds import FeedsAPI


def _api_with_request(method: str, body: bytes, logged_in_staff: str | None) -> FeedsAPI:
    headers = {}
    if logged_in_staff:
        headers["canvas-logged-in-user-id"] = logged_in_staff
    request = MagicMock(
        method=method,
        body=body,
        headers=headers,
        path_params={},
    )
    api = FeedsAPI.__new__(FeedsAPI)
    api.request = request
    api.secrets = {}
    return api


def test_post_rejects_when_unauthenticated() -> None:
    api = _api_with_request("POST", b'{"ics_url":"https://x.com/x.ics"}', logged_in_staff=None)
    responses = api.create_feed()
    assert responses[0].status_code == 401


def test_post_rejects_non_https() -> None:
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed"):
        api = _api_with_request(
            "POST", b'{"ics_url":"http://insecure.example.com/cal.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400


def test_post_rejects_javascript_scheme() -> None:
    api = _api_with_request(
        "POST", b'{"ics_url":"javascript:alert(1)"}',
        logged_in_staff="staff-abc",
    )
    responses = api.create_feed()
    assert responses[0].status_code == 400


def test_post_rejects_non_ics_body() -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed"),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(body=b"<html>not ics</html>", etag=None, last_modified=None)
        api = _api_with_request(
            "POST", b'{"ics_url":"https://x.com/x.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400


def test_post_creates_feed_when_valid() -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            etag=None, last_modified=None,
        )
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST", b'{"ics_url":"https://x.com/x.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()

    assert responses[0].status_code == 200
    MockFeed.assert_called_once()
    kwargs = MockFeed.call_args.kwargs
    assert kwargs["staff_id"] == "staff-abc"
    assert kwargs["ics_url"] == "https://x.com/x.ics"


def test_post_ignores_staff_id_in_body() -> None:
    """Even if the body claims a different staff_id, the session is authoritative."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://x.com/x.ics","staff_id":"impersonated"}',
            logged_in_staff="staff-real",
        )
        api.create_feed()
    assert MockFeed.call_args.kwargs["staff_id"] == "staff-real"


def test_delete_idempotent_when_no_feed() -> None:
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request("POST", b"{}", logged_in_staff="staff-abc")
        responses = api.delete_feed()
    assert responses[0].status_code == 200


def test_delete_removes_feed_and_emits_delete_effects() -> None:
    feed = MagicMock(staff_id="staff-abc")
    imported = [
        MagicMock(canvas_event_id="evt-1"),
        MagicMock(canvas_event_id="evt-2"),
    ]
    with (
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.ImportedEvent") as MockImported,
    ):
        MockFeed.objects.filter.return_value.first.return_value = feed
        MockImported.objects.filter.return_value = imported
        api = _api_with_request("POST", b"{}", logged_in_staff="staff-abc")
        responses = api.delete_feed()
    # Expect 2 Event.delete effects + 1 JSONResponse
    effects_emitted = [r for r in responses if hasattr(r, "type")]
    assert len(effects_emitted) == 2
    feed.delete.assert_called_once()
