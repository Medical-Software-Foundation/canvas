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
    note_exists: bool = True,
) -> LiveObservationsChannel:
    ch = LiveObservationsChannel.__new__(LiveObservationsChannel)
    ch.websocket = SimpleNamespace(
        logged_in_user=logged_in_user,
        channel=channel_name,
    )
    cache_mock = MagicMock()
    cache_mock.get.return_value = cache_session
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    note_mgr.filter.return_value.exists.return_value = note_exists
    return ch


def test_authenticate_rejects_when_no_user() -> None:
    ch = _make_channel(logged_in_user=None, channel_name="abc_def")
    assert ch.authenticate() is False


def test_authenticate_rejects_non_staff_user() -> None:
    ch = _make_channel(
        logged_in_user={"type": "Patient"}, channel_name="abc_def"
    )
    assert ch.authenticate() is False


def test_authenticate_per_note_spravato_channel_allows_when_note_exists() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="spravato_notify_abcd_1234",
        note_exists=True,
    )
    assert ch.authenticate() is True
    note_mgr = sys.modules["canvas_sdk.v1.data.note"].Note.objects
    # The note UUID is reconstructed from the channel name (underscores → hyphens).
    note_mgr.filter.assert_called_with(id="abcd-1234")


def test_authenticate_per_note_spravato_channel_rejects_unknown_note() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="spravato_notify_does_not_exist",
        note_exists=False,
    )
    assert ch.authenticate() is False


def test_authenticate_legacy_global_spravato_channel_falls_through_to_session() -> None:
    # Regression: the previous `spravato_notify` open channel let any staff in
    # the org subscribe. It must no longer be treated as open; with no session
    # cached for that name, auth must fail.
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="spravato_notify",
        cache_session=None,
    )
    assert ch.authenticate() is False


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


def test_authenticate_allows_session_channel_regardless_of_staff_match() -> None:
    ch = _make_channel(
        logged_in_user={"id": "other-staff", "type": "Staff"},
        channel_name="a_b_c",
        cache_session={"note_id": 1, "staff_id": "s1"},
    )
    assert ch.authenticate() is True
