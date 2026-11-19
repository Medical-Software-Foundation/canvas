"""Tests for the note-footer 'Send to Photon' button."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from photon_integration.handlers.send_button import _CACHE_BUST, PhotonSendButton

MODULE = "photon_integration.handlers.send_button"


def _button(context):
    button = PhotonSendButton.__new__(PhotonSendButton)
    button.event = SimpleNamespace(context=context)
    return button


def test_handle_launches_send_modal_with_note():
    button = _button({"note_id": 4567})
    with patch(f"{MODULE}.LaunchModalEffect") as modal:
        modal.return_value.apply.return_value = "MODAL_EFFECT"
        result = button.handle()

    assert result == ["MODAL_EFFECT"]
    kwargs = modal.call_args.kwargs
    assert kwargs["url"] == (
        f"/plugin-io/api/photon_integration/photon/send?note_id=4567&v={_CACHE_BUST}"
    )
    assert kwargs["target"] == modal.TargetType.RIGHT_CHART_PANE_LARGE


def test_button_metadata():
    assert PhotonSendButton.BUTTON_TITLE == "Send to Photon"
    assert PhotonSendButton.BUTTON_KEY == "PHOTON_SEND"
