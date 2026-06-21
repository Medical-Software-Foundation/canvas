"""Tests for ChannelManager: config fail-closed, open, renew-if-needed, expiration parsing."""

from types import SimpleNamespace

import arrow
import pytest

from gcal_sync.channels import ChannelConfigError, ChannelManager, webhook_address, WEBHOOK_PATH

SECRETS = {
    "GOOGLE_CALENDAR_WEBHOOK_TOKEN": "tok",
    "GOOGLE_WEBHOOK_BASE_URL": "https://demo.canvasmedical.com",
    "GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "svc@x.iam", "private_key": "KEY"}',
}


def test_webhook_address_built_from_base():
    assert webhook_address(SECRETS) == f"https://demo.canvasmedical.com{WEBHOOK_PATH}"


def test_webhook_address_fails_closed_without_base():
    with pytest.raises(ChannelConfigError):
        webhook_address({})


def test_manager_fails_closed_without_token():
    with pytest.raises(ChannelConfigError):
        ChannelManager(
            {
                "GOOGLE_WEBHOOK_BASE_URL": "https://x",
                "GOOGLE_SERVICE_ACCOUNT_JSON": '{"client_email": "s", "private_key": "k"}',
            }
        )


def test_open_channel_stops_existing_and_creates(mocker):
    wc = mocker.patch("gcal_sync.channels.WatchChannel")
    wc.objects.filter.return_value = []  # no existing channels to stop
    client = SimpleNamespace(
        watch_events=mocker.Mock(return_value={"resourceId": "r", "expiration": "1893456000000"}),
        stop_channel=mocker.Mock(),
    )
    mgr = ChannelManager(SECRETS, client_factory=lambda c: client)
    mgr.open_channel("c1")
    client.watch_events.assert_called_once()
    wc.objects.create.assert_called_once()


def test_renew_if_needed_opens_when_missing(mocker):
    wc = mocker.patch("gcal_sync.channels.WatchChannel")
    wc.objects.filter.return_value.order_by.return_value.first.return_value = None
    mgr = ChannelManager(SECRETS, client_factory=lambda c: SimpleNamespace())
    opened = mocker.patch.object(mgr, "open_channel")
    assert mgr.renew_if_needed("c1") is True
    opened.assert_called_once()


def test_renew_if_needed_skips_when_healthy(mocker):
    wc = mocker.patch("gcal_sync.channels.WatchChannel")
    healthy = SimpleNamespace(expiration=arrow.utcnow().shift(days=5).datetime)
    wc.objects.filter.return_value.order_by.return_value.first.return_value = healthy
    mgr = ChannelManager(SECRETS, client_factory=lambda c: SimpleNamespace())
    opened = mocker.patch.object(mgr, "open_channel")
    assert mgr.renew_if_needed("c1") is False
    opened.assert_not_called()


def test_parse_expiration_valid_and_invalid():
    assert ChannelManager._parse_expiration("1893456000000") is not None
    assert ChannelManager._parse_expiration("not-a-number") is None
    assert ChannelManager._parse_expiration(None) is None
