import json
from unittest.mock import MagicMock

from note_lifecycle_example.handlers.footer_configuration import HideDefaultStateButtons

from canvas_generated.messages.effects_pb2 import EffectType
from canvas_sdk.events import EventType


def test_handler_responds_to_footer_configuration() -> None:
    """The handler answers the note footer configuration request."""
    assert (
        EventType.Name(EventType.NOTE_FOOTER__GET_CONFIGURATION)
        == HideDefaultStateButtons.RESPONDS_TO
    )


def test_handler_hides_default_state_buttons() -> None:
    """The handler returns a footer configuration that hides the default state buttons."""
    effects = HideDefaultStateButtons(event=MagicMock()).compute()

    assert len(effects) == 1
    assert effects[0].type == EffectType.NOTE_FOOTER__CONFIGURATION
    assert json.loads(effects[0].payload)["data"]["hide_default_state_buttons"] is True
