from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from vitalstream.channels.live_observations import LiveObservationsChannel


def _make_channel(
    *,
    logged_in_user: dict | None,
    channel_name: str,
    session_exists: bool = True,
    note_exists: bool = True,
) -> LiveObservationsChannel:
    ch = LiveObservationsChannel.__new__(LiveObservationsChannel)
    ch.websocket = SimpleNamespace(
        logged_in_user=logged_in_user,
        channel=channel_name,
    )

    session_mgr = sys.modules["vitalstream.models"].VitalstreamSession.objects
    session_mgr.filter.return_value.exists.return_value = session_exists

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


def test_authenticate_rejects_session_channel_when_session_missing() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="a_b_c",
        session_exists=False,
    )
    assert ch.authenticate() is False


def test_authenticate_allows_session_channel_when_session_exists() -> None:
    ch = _make_channel(
        logged_in_user={"id": "s1", "type": "Staff"},
        channel_name="a_b_c",
        session_exists=True,
    )
    assert ch.authenticate() is True
    session_mgr = sys.modules["vitalstream.models"].VitalstreamSession.objects
    # session_id reconstructed from channel name (underscores → hyphens).
    session_mgr.filter.assert_called_with(session_id="a-b-c")
