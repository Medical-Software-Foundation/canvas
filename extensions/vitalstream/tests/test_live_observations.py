from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from vitalstream.channels.live_observations import LiveObservationsChannel


def _make_channel(
    *,
    logged_in_user: dict | None,
    channel_name: str,
    cache_session: dict | None = None,
) -> LiveObservationsChannel:
    ch = LiveObservationsChannel.__new__(LiveObservationsChannel)
    ch.websocket = SimpleNamespace(
        logged_in_user=logged_in_user,
        channel=channel_name,
    )
    cache_mock = MagicMock()
    cache_mock.get.return_value = cache_session
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock
    return ch


def test_authenticate_rejects_when_no_user() -> None:
    ch = _make_channel(logged_in_user=None, channel_name="abc_def")
    assert ch.authenticate() is False


def test_authenticate_rejects_non_staff_user() -> None:
    ch = _make_channel(
        logged_in_user={"type": "Patient"}, channel_name="abc_def"
    )
    assert ch.authenticate() is False


def test_authenticate_allows_open_channel_without_session() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="spravato_notify",
    )
    assert ch.authenticate() is True


def test_authenticate_rejects_session_channel_when_session_missing() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="a_b_c",
        cache_session=None,
    )
    assert ch.authenticate() is False


def test_authenticate_allows_session_channel_when_staff_matches() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="a_b_c",
        cache_session={"note_id": 1, "staff_id": "s1"},
    )
    assert ch.authenticate() is True


def test_authenticate_rejects_session_channel_when_staff_does_not_match() -> None:
    ch = _make_channel(
        logged_in_user={"id": "other-staff", "type": "Staff"},
        channel_name="a_b_c",
        cache_session={"note_id": 1, "staff_id": "s1"},
    )
    assert ch.authenticate() is False
