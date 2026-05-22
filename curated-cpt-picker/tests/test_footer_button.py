"""Tests for the NOTE_FOOTER ActionButton.

Verifies the button emits a LaunchModalEffect pointing at the picker
endpoint with the current note_id encoded in the URL.
"""

import json

from types import SimpleNamespace

from canvas_sdk.effects import EffectType
from canvas_sdk.handlers.action_button import ActionButton

from curated_cpt_picker.protocols.footer_button import CuratedCptFooterButton


def _make_event(note_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(context={"note_id": note_id} if note_id else {})


def test_button_metadata_targets_note_footer() -> None:
    """The button must register in the NOTE_FOOTER, not some other location —
    otherwise providers won't find it in the right workflow."""
    assert CuratedCptFooterButton.BUTTON_LOCATION == ActionButton.ButtonLocation.NOTE_FOOTER
    assert CuratedCptFooterButton.BUTTON_TITLE == "Quick add codes"
    assert CuratedCptFooterButton.BUTTON_KEY == "CURATED_CPT_PICKER_OPEN"


def test_handle_emits_launch_modal_with_note_id() -> None:
    handler = CuratedCptFooterButton(event=_make_event("abc-123"))
    effects = handler.handle()

    assert len(effects) == 1
    effect = effects[0]
    assert effect.type == EffectType.LAUNCH_MODAL

    # Effect.payload is JSON of {"data": {url, content, target, title}}.
    payload = json.loads(effect.payload)
    assert "abc-123" in payload["data"]["url"]
    assert payload["data"]["url"].startswith("/plugin-io/api/curated_cpt_picker/picker")


def test_handle_returns_no_effects_when_note_id_missing() -> None:
    """If the button event arrives without a note_id, we can't build a useful
    URL — return [] rather than emitting a broken modal."""
    handler = CuratedCptFooterButton(event=_make_event(None))
    assert handler.handle() == []
