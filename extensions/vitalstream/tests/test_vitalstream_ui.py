from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vitalstream.applications.vitalstream_ui import VitalstreamUILauncher


def _make_launcher(
    *,
    note_id: str = "note-42",
    staff_id: str = "staff-7",
    actor_is_staff: bool = True,
    actor_has_instance: bool = True,
) -> VitalstreamUILauncher:
    launcher = VitalstreamUILauncher.__new__(VitalstreamUILauncher)
    launcher.context = {"note_id": note_id}

    instance = MagicMock()
    instance.is_staff = actor_is_staff
    instance.person_subclass.id = staff_id

    actor = MagicMock()
    actor.instance = instance if actor_has_instance else None

    launcher.event = SimpleNamespace(actor=actor)
    return launcher


def test_visible_returns_false_when_note_is_locked() -> None:
    launcher = _make_launcher()
    note_state = SimpleNamespace(state="LOCKED")
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.CurrentNoteStateEvent.objects.get.return_value = note_state
    assert launcher.visible() is False


def test_visible_returns_true_when_note_unlocked() -> None:
    launcher = _make_launcher()
    note_state = SimpleNamespace(state="NEW")
    note_mod = sys.modules["canvas_sdk.v1.data.note"]
    note_mod.CurrentNoteStateEvent.objects.get.return_value = note_state
    assert launcher.visible() is True


def test_handle_raises_when_actor_is_not_staff() -> None:
    launcher = _make_launcher(actor_is_staff=False)
    cache_mock = MagicMock()
    cache_mock.get.return_value = None
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock
    with pytest.raises(RuntimeError, match="Launching user must be Staff"):
        launcher.handle()


def test_handle_returns_launch_modal_effect_for_staff_actor() -> None:
    launcher = _make_launcher()
    cache_mock = MagicMock()
    cache_mock.get.return_value = None  # no collision
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    effects = launcher.handle()

    assert len(effects) == 1
    effect = effects[0]
    assert effect.kwargs["target"] == "RIGHT_CHART_PANE_LARGE"
    assert effect.kwargs["url"].startswith(
        "/plugin-io/api/vitalstream/vitalstream-ui/sessions/"
    )
    assert effect.kwargs["url"].endswith("/")


def test_get_new_session_id_stores_in_cache_on_first_try() -> None:
    launcher = _make_launcher()
    cache_mock = MagicMock()
    cache_mock.get.return_value = None
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    session_id = launcher.get_new_session_id("note-42", "staff-7")

    # Session should be set with the note/staff payload and a TTL.
    set_call = cache_mock.set.call_args
    key, value = set_call.args[0], set_call.args[1]
    assert key == f"session_id:{session_id}"
    assert value == {"note_id": "note-42", "staff_id": "staff-7"}
    assert set_call.kwargs.get("timeout_seconds") == 60 * 60 * 24 * 2


def test_get_new_session_id_regenerates_on_collision() -> None:
    launcher = _make_launcher()
    cache_mock = MagicMock()
    # Simulate one collision then a miss (i.e. id is free).
    cache_mock.get.side_effect = [{"existing": "session"}, None]
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    session_id = launcher.get_new_session_id("note-1", "staff-1")
    assert session_id
    assert cache_mock.get.call_count == 2
    assert cache_mock.set.call_count == 1


def test_get_new_session_id_raises_when_collisions_exceed_threshold() -> None:
    launcher = _make_launcher()
    cache_mock = MagicMock()
    # Always return a session — collision every time.
    cache_mock.get.return_value = {"existing": "session"}
    sys.modules["canvas_sdk.caching.plugins"].get_cache.return_value = cache_mock

    with pytest.raises(RuntimeError, match="Could not generate a session identifier"):
        launcher.get_new_session_id("note-1", "staff-1")
