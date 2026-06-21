"""Tests for the GoogleWebhook endpoint: fail-closed auth + receive() routing."""

from http import HTTPStatus
from types import SimpleNamespace

from gcal_sync.google.client import GoogleApiError
from gcal_sync.routes.webhook import GoogleWebhook


def _wh(secrets=None, headers=None):
    wh = GoogleWebhook.__new__(GoogleWebhook)
    wh.secrets = secrets or {}
    wh.request = SimpleNamespace(headers=headers or {})
    return wh


def test_authenticate_fails_closed_without_token():
    assert (
        _wh({"GOOGLE_CALENDAR_WEBHOOK_TOKEN": ""}, {"x-goog-channel-token": "t"}).authenticate(None)
        is False
    )


def test_authenticate_rejects_mismatch():
    assert (
        _wh({"GOOGLE_CALENDAR_WEBHOOK_TOKEN": "secret"}, {"x-goog-channel-token": "wrong"}).authenticate(
            None
        )
        is False
    )


def test_authenticate_accepts_matching_token():
    assert (
        _wh({"GOOGLE_CALENDAR_WEBHOOK_TOKEN": "secret"}, {"x-goog-channel-token": "secret"}).authenticate(
            None
        )
        is True
    )


def test_receive_sync_handshake_is_acked():
    resp = _wh(headers={"x-goog-resource-state": "sync"}).receive()
    assert resp[0].status_code == HTTPStatus.OK


def test_receive_unknown_channel_is_acked(mocker):
    wc = mocker.patch("gcal_sync.routes.webhook.WatchChannel")
    wc.objects.filter.return_value.first.return_value = None
    resp = _wh(headers={"x-goog-channel-id": "c", "x-goog-resource-state": "exists"}).receive()
    assert resp[0].status_code == HTTPStatus.OK


def test_receive_known_channel_processes_delta(mocker):
    wc = mocker.patch("gcal_sync.routes.webhook.WatchChannel")
    wc.objects.filter.return_value.first.return_value = SimpleNamespace(google_calendar_id="c1")
    inbound = mocker.patch("gcal_sync.routes.webhook.InboundSync").return_value
    inbound.process_calendar.return_value = ({}, ["HOLD"])
    mocker.patch("gcal_sync.routes.webhook.allowed_google_changes", return_value=set())
    resp = _wh(
        {"GOOGLE_CALENDAR_WEBHOOK_TOKEN": "t"},
        headers={"x-goog-channel-id": "c", "x-goog-resource-state": "exists"},
    ).receive()
    assert "HOLD" in resp
    assert resp[-1].status_code == HTTPStatus.OK


def test_receive_delta_failure_returns_503(mocker):
    wc = mocker.patch("gcal_sync.routes.webhook.WatchChannel")
    wc.objects.filter.return_value.first.return_value = SimpleNamespace(google_calendar_id="c1")
    inbound = mocker.patch("gcal_sync.routes.webhook.InboundSync").return_value
    inbound.process_calendar.side_effect = GoogleApiError(500, "boom")
    mocker.patch("gcal_sync.routes.webhook.allowed_google_changes", return_value=set())
    resp = _wh(
        {"GOOGLE_CALENDAR_WEBHOOK_TOKEN": "t"},
        headers={"x-goog-channel-id": "c", "x-goog-resource-state": "exists"},
    ).receive()
    assert resp[0].status_code == HTTPStatus.SERVICE_UNAVAILABLE
