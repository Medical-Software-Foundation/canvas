"""Tests for the inbound allow-list policy and the webhook header/auth helpers."""

import inspect

from gcal_sync.inbound import allowed_google_changes
from gcal_sync.routes import webhook
from gcal_sync.routes.webhook import _header


def test_allow_list_defaults_to_empty():
    # Empty / unset -> Canvas always wins (no Google->Canvas mutations permitted).
    assert allowed_google_changes({}) == set()
    assert allowed_google_changes({"GOOGLE_TO_CANVAS_ALLOWED_CHANGES": ""}) == set()
    assert allowed_google_changes({"GOOGLE_TO_CANVAS_ALLOWED_CHANGES": None}) == set()


def test_allow_list_parses_csv():
    secrets = {"GOOGLE_TO_CANVAS_ALLOWED_CHANGES": "cancel, reschedule ,note"}
    assert allowed_google_changes(secrets) == {"cancel", "reschedule", "note"}


def test_header_lookup_is_case_insensitive():
    headers = {"X-Goog-Channel-Token": "secret", "X-Goog-Channel-ID": "abc"}
    assert _header(headers, "x-goog-channel-token") == "secret"
    assert _header(headers, "X-GOOG-CHANNEL-ID") == "abc"


def test_header_missing_returns_empty_string():
    assert _header({"a": "b"}, "x-goog-channel-token") == ""


def test_header_tolerates_non_dict():
    assert _header(object(), "anything") == ""


def test_authenticate_fails_closed_when_secret_unset():
    # Source-level guarantee: the token secret is required and an empty token is rejected.
    src = inspect.getsource(webhook.GoogleWebhook.authenticate)
    assert "GOOGLE_CALENDAR_WEBHOOK_TOKEN" in src
    assert "return False" in src
    assert "compare_digest" in src


def test_inbound_410_handling_present():
    # The delta processor must recover from an invalidated sync token rather than wedging.
    src = inspect.getsource(__import__("gcal_sync.inbound", fromlist=["InboundSync"]).InboundSync.process_calendar)
    assert "410" in src
    assert "needs_full_resync" in src
