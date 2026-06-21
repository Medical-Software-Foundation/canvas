"""Tests for watch-channel config (fail-closed) and expiration parsing/renewal timing."""

from datetime import timedelta
from types import SimpleNamespace

import arrow
import pytest

from gcal_sync.channels import (
    RENEW_WITHIN_SECONDS,
    WEBHOOK_PATH,
    ChannelConfigError,
    ChannelManager,
    webhook_address,
)


def test_webhook_address_builds_full_url():
    secrets = {"GOOGLE_WEBHOOK_BASE_URL": "https://demo.canvasmedical.com"}
    assert webhook_address(secrets) == f"https://demo.canvasmedical.com{WEBHOOK_PATH}"


def test_webhook_address_strips_trailing_slash():
    secrets = {"GOOGLE_WEBHOOK_BASE_URL": "https://demo.canvasmedical.com/"}
    assert webhook_address(secrets) == f"https://demo.canvasmedical.com{WEBHOOK_PATH}"


def test_webhook_address_fails_closed_when_unset():
    with pytest.raises(ChannelConfigError):
        webhook_address({})


def test_parse_expiration_converts_ms_epoch_to_datetime():
    # Google returns expiration as a string of milliseconds since the epoch.
    expected = arrow.get(1_700_000_000)
    parsed = ChannelManager._parse_expiration("1700000000000")
    assert arrow.get(parsed) == expected


def test_parse_expiration_handles_garbage():
    assert ChannelManager._parse_expiration("not-a-number") is None
    assert ChannelManager._parse_expiration(None) is None


def test_expiring_soon_true_for_missing_expiration():
    channel = SimpleNamespace(expiration=None)
    assert ChannelManager._expiring_soon(channel) is True


def test_expiring_soon_true_within_window():
    soon = arrow.utcnow().shift(seconds=RENEW_WITHIN_SECONDS - 3600).datetime
    assert ChannelManager._expiring_soon(SimpleNamespace(expiration=soon)) is True


def test_expiring_soon_false_when_far_out():
    far = arrow.utcnow().shift(seconds=RENEW_WITHIN_SECONDS).datetime + timedelta(days=1)
    assert ChannelManager._expiring_soon(SimpleNamespace(expiration=far)) is False
