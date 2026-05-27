from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from vitalstream.applications.vitalstream_ui import VitalstreamUILauncher


def _make_launcher(note_id: str = "42") -> VitalstreamUILauncher:
    launcher = VitalstreamUILauncher.__new__(VitalstreamUILauncher)
    launcher.context = {"note_id": note_id}
    return launcher


def test_visible_returns_false_when_note_is_locked() -> None:
    launcher = _make_launcher()
    note_state = SimpleNamespace(state="LOCKED")
    sys.modules["canvas_sdk.v1.data.note"].CurrentNoteStateEvent.objects.get.return_value = note_state
    assert launcher.visible() is False


def test_visible_returns_true_when_note_unlocked() -> None:
    launcher = _make_launcher()
    note_state = SimpleNamespace(state="NEW")
    sys.modules["canvas_sdk.v1.data.note"].CurrentNoteStateEvent.objects.get.return_value = note_state
    assert launcher.visible() is True


def test_handle_returns_launch_modal_pointing_at_the_note() -> None:
    """The button itself does NO DB work — it just opens the UI scoped to the
    note. The session row is resolved (or created) inside the UI SimpleAPI
    handler, which is the proven pattern for CustomModel persistence."""
    launcher = _make_launcher(note_id="42")
    VitalstreamSession = sys.modules["vitalstream.models"].VitalstreamSession

    effects = launcher.handle()

    assert len(effects) == 1
    effect = effects[0]
    assert effect.kwargs["target"] == "RIGHT_CHART_PANE_LARGE"
    assert effect.kwargs["url"] == (
        "/plugin-io/api/vitalstream/vitalstream-ui/notes/42/"
    )
    # No session was constructed at button-press time.
    VitalstreamSession.assert_not_called()
