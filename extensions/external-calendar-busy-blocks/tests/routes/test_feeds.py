import json
from unittest.mock import MagicMock, patch

import pytest

from external_calendar_busy_blocks.routes.feeds import FeedsAPI


def _api_with_request(
    method: str,
    body: bytes,
    logged_in_staff: str | None,
    secrets: dict | None = None,
    query_params: dict | None = None,
) -> FeedsAPI:
    headers = {}
    if logged_in_staff:
        headers["canvas-logged-in-user-id"] = logged_in_staff
    request = MagicMock(
        method=method,
        body=body,
        headers=headers,
        path_params={},
        query_params=query_params or {},
    )
    api = FeedsAPI.__new__(FeedsAPI)
    api.request = request
    api.secrets = secrets or {}
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
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics"}',
            logged_in_staff="staff-abc",
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400
    # Reached the body-probe stage (host was allowlisted) and rejected the HTML.
    mock_fetch.assert_called_once()


def test_post_creates_feed_when_valid() -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
            etag=None, last_modified=None,
        )
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics"}',
            # Header arrives as a UUID with dashes; must be canonicalized to the
            # dashless form that matches Staff.id (uuid4().hex).
            logged_in_staff="00000000-0000-0000-0000-000000000001",
        )
        responses = api.create_feed()

    assert responses[0].status_code == 200
    MockFeed.assert_called_once()
    kwargs = MockFeed.call_args.kwargs
    assert kwargs["staff_id"] == "00000000000000000000000000000001"
    assert kwargs["ics_url"] == "https://calendar.google.com/calendar/ical/me/basic.ics"


def test_post_non_admin_ignores_staff_id_in_body() -> None:
    """A non-admin's body staff_id is ignored; the session stays authoritative."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://outlook.office365.com/owa/calendar/x/calendar.ics",'
            b'"staff_id":"00000000000000000000000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000002",
            secrets={},  # not an admin
        )
        api.create_feed()
    assert MockFeed.call_args.kwargs["staff_id"] == "00000000000000000000000000000002"


def test_post_admin_targets_other_staff() -> None:
    """An admin's body staff_id is honored: the feed is keyed to the target."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])) as mock_get_cal,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics",'
            b'"staff_id":"00000000-0000-0000-0000-000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        )
        api.create_feed()
    assert MockFeed.call_args.kwargs["staff_id"] == "00000000000000000000000000000099"
    assert mock_get_cal.call_args.args[0] == "00000000000000000000000000000099"


def test_post_admin_returns_400_when_calendar_unresolvable() -> None:
    """If the target staff can't be resolved, no feed is written and we 400."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", None, None)
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics",'
            b'"staff_id":"00000000000000000000000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        )
        responses = api.create_feed()
    assert responses[0].status_code == 400
    MockFeed.assert_not_called()


def test_delete_admin_targets_other_staff() -> None:
    feed = MagicMock(staff_id="00000000000000000000000000000099")
    with (
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.ImportedEvent") as MockImported,
    ):
        MockFeed.objects.filter.return_value.first.return_value = feed
        MockImported.objects.filter.return_value = []
        api = _api_with_request(
            "POST",
            b'{"staff_id":"00000000-0000-0000-0000-000000000099"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        )
        responses = api.delete_feed()
    # Feed and imported-event lookups were scoped to the target staff id.
    assert MockFeed.objects.filter.call_args.kwargs["staff_id"] == "00000000000000000000000000000099"
    assert responses[-1].status_code == 200
    feed.delete.assert_called_once()


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


# --- SSRF: host allowlist -----------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata
        "https://127.0.0.1/x.ics",                     # loopback
        "https://10.0.0.5/x.ics",                      # RFC1918
        "https://192.168.1.1/x.ics",                   # RFC1918
        "https://localhost/x.ics",                     # internal name
        "https://internal-service.corp/x.ics",         # arbitrary internal host
        "https://evil.com/x.ics",                      # arbitrary public host
        "https://calendar.google.com.evil.com/x.ics",  # suffix-spoof attempt
        "https://notgoogle.com/x.ics",
        # Double-@ userinfo bypass: the client dials the host after the LAST
        # '@', so the allowlist must read the same host (not the one before it).
        "https://attacker.com@calendar.google.com:443@169.254.169.254/latest/meta-data/",
        "https://x@calendar.google.com:80@127.0.0.1/x.ics",
        "https://x@outlook.office365.com:443@10.0.0.5/x.ics",
        "https://x@p31-caldav.icloud.com:443@internal-postgres:5432/x.ics",
    ],
)
def test_post_rejects_disallowed_hosts(url) -> None:
    """SSRF guard: only known calendar-provider hosts may be fetched."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed"),
    ):
        body = ('{"ics_url":"' + url + '"}').encode()
        api = _api_with_request("POST", body, logged_in_staff="staff-abc")
        responses = api.create_feed()
    assert responses[0].status_code == 400
    # The fetch must never be issued for a disallowed host.
    mock_fetch.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://calendar.google.com/calendar/ical/me/basic.ics",
        "https://outlook.office365.com/owa/calendar/x/calendar.ics",
        "https://outlook.live.com/owa/calendar/x/calendar.ics",
        "https://p31-caldav.icloud.com/published/2/x",
        "https://CALENDAR.GOOGLE.COM/calendar/ical/me/basic.ics",  # case-insensitive
    ],
)
def test_post_accepts_allowlisted_hosts(url) -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", etag=None, last_modified=None
        )
        MockFeed.objects.filter.return_value.first.return_value = None
        body = ('{"ics_url":"' + url + '"}').encode()
        api = _api_with_request("POST", body, logged_in_staff="staff-abc")
        responses = api.create_feed()
    assert responses[0].status_code == 200
    mock_fetch.assert_called_once()


@pytest.mark.parametrize(
    "url",
    [
        "https://calendar.google.com\t@169.254.169.254/latest/meta-data/",  # tab
        "https://calendar.google.com @169.254.169.254/x.ics",               # space
        "https://calendar.google.com\n@169.254.169.254/x.ics",              # LF
        "https://calendar.google.com\r@169.254.169.254/x.ics",              # CR
        "https://calendar.google.com\xa0@169.254.169.254/x.ics",            # NBSP
    ],
)
def test_post_rejects_whitespace_injection(url) -> None:
    """SSRF guard: a URL with internal whitespace must be rejected before the
    host check, since requests percent-encodes it and dials the trailing host."""
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed"),
    ):
        body = json.dumps({"ics_url": url}).encode()
        api = _api_with_request("POST", body, logged_in_staff="staff-abc")
        responses = api.create_feed()
    assert responses[0].status_code == 400
    mock_fetch.assert_not_called()


def test_connect_provisions_calendar_when_missing() -> None:
    cal_effect = MagicMock()
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-new", [cal_effect])) as mock_get_cal,
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", etag=None, last_modified=None
        )
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
        )
        responses = api.create_feed()

    # Provisioned with the canonicalized session staff id.
    assert mock_get_cal.call_args.args[0] == "00000000000000000000000000000001"
    # The Calendar create effect is returned before the JSONResponse.
    assert responses[0] is cal_effect
    assert responses[-1].status_code == 200


def test_connect_no_calendar_effect_when_exists() -> None:
    with (
        patch("external_calendar_busy_blocks.routes.feeds.fetch_feed") as mock_fetch,
        patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed,
        patch("external_calendar_busy_blocks.routes.feeds.get_admin_calendar_id",
              return_value=("cal-1", [])),
    ):
        from external_calendar_busy_blocks.http.fetcher import FetchOk
        mock_fetch.return_value = FetchOk(
            body=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", etag=None, last_modified=None
        )
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "POST",
            b'{"ics_url":"https://calendar.google.com/calendar/ical/me/basic.ics"}',
            logged_in_staff="00000000-0000-0000-0000-000000000001",
        )
        responses = api.create_feed()

    # Only the JSONResponse — no effects emitted.
    effects_emitted = [r for r in responses if hasattr(r, "type")]
    assert effects_emitted == []
    assert responses[0].status_code == 200


def test_status_requires_admin() -> None:
    api = _api_with_request(
        "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000002",
        secrets={},  # not an admin
        query_params={"staff_id": "00000000000000000000000000000099"},
    )
    responses = api.feed_status()
    assert responses[0].status_code == 403


def test_status_requires_staff_id() -> None:
    api = _api_with_request(
        "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000001",
        secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
        query_params={},
    )
    responses = api.feed_status()
    assert responses[0].status_code == 400


def test_status_reports_connected_feed_without_url() -> None:
    feed = MagicMock(is_active=True, last_sync_at="2026-07-11T00:00:00Z", last_error=None)
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = feed
        api = _api_with_request(
            "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
            query_params={"staff_id": "00000000-0000-0000-0000-000000000099"},
        )
        responses = api.feed_status()
    assert responses[0].status_code == 200
    body = json.loads(responses[0].content)
    assert body["connected"] is True
    assert "ics_url" not in body
    # Lookup was scoped to the canonicalized target id.
    assert MockFeed.objects.filter.call_args.kwargs["staff_id"] == "00000000000000000000000000000099"


def test_status_reports_no_feed() -> None:
    with patch("external_calendar_busy_blocks.routes.feeds.StaffCalendarFeed") as MockFeed:
        MockFeed.objects.filter.return_value.first.return_value = None
        api = _api_with_request(
            "GET", b"", logged_in_staff="00000000-0000-0000-0000-000000000001",
            secrets={"ADMIN_STAFF_IDS": "00000000000000000000000000000001"},
            query_params={"staff_id": "00000000000000000000000000000099"},
        )
        responses = api.feed_status()
    body = json.loads(responses[0].content)
    assert body["connected"] is False
