from unittest.mock import MagicMock, patch

import pytest

from external_calendar_busy_blocks.http.fetcher import (
    FetchOk,
    NotModified,
    Unauthorized,
    NotFound,
    TransientError,
    fetch_feed,
    redact_url,
)


def test_redact_strips_query_token() -> None:
    url = "https://calendar.google.com/calendar/ical/me%40example.com/private-abc123def456ghijkl/basic.ics"
    redacted = redact_url(url)
    assert "abc123def456" not in redacted
    assert "calendar.google.com" in redacted
    assert "***" in redacted


def test_redact_strips_query_string_secret() -> None:
    url = "https://outlook.live.com/owa/calendar/ics?path=/calendar&secret=verylongsecretstring1234567890"
    redacted = redact_url(url)
    assert "verylongsecretstring" not in redacted
    assert "outlook.live.com" in redacted


def test_fetch_200_returns_ok() -> None:
    response = MagicMock(
        status_code=200,
        content=b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
        headers={"ETag": '"abc"', "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"},
    )
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, FetchOk)
    assert result.body.startswith(b"BEGIN:VCALENDAR")
    assert result.etag == '"abc"'
    assert result.last_modified == "Mon, 01 Jun 2026 00:00:00 GMT"


def test_fetch_304_returns_not_modified() -> None:
    response = MagicMock(status_code=304, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag='"abc"', last_modified=None)
    assert isinstance(result, NotModified)


def test_fetch_401_returns_unauthorized() -> None:
    response = MagicMock(status_code=401, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, Unauthorized)


def test_fetch_404_returns_not_found() -> None:
    response = MagicMock(status_code=404, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, NotFound)


def test_fetch_500_returns_transient() -> None:
    response = MagicMock(status_code=503, content=b"", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, TransientError)


def test_fetch_exception_returns_transient() -> None:
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.side_effect = RuntimeError("network down")
        result = fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    assert isinstance(result, TransientError)


def test_fetch_calls_get_with_only_url_and_headers() -> None:
    # Regression: canvas_sdk's Http.get(url, headers=...) takes no `timeout`
    # kwarg. Passing one raises TypeError at runtime (swallowed into a
    # TransientError), silently breaking every real fetch. Lock the call shape.
    response = MagicMock(status_code=200, content=b"BEGIN:VCALENDAR\r\n", headers={})
    with patch("external_calendar_busy_blocks.http.fetcher.Http") as MockHttp:
        MockHttp.return_value.get.return_value = response
        fetch_feed("https://example.com/x.ics", etag=None, last_modified=None)
    _, kwargs = MockHttp.return_value.get.call_args
    assert "timeout" not in kwargs
    assert set(kwargs) == {"headers"}
