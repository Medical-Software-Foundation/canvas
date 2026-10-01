from canvas_sdk.effects import Effect
from canvas_sdk.effects.note_footer_configuration import NoteFooterConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers import BaseHandler


class HideDefaultStateButtons(BaseHandler):
    """Hide Canvas's native footer state buttons so this plugin's state buttons replace them.

    Suppression is configured at the note level (not per button): the home-app requests the
    footer configuration once per note via ``NOTE_FOOTER__GET_CONFIGURATION``, and this
    handler answers with ``hide_default_state_buttons=True``.
    """

    RESPONDS_TO = EventType.Name(EventType.NOTE_FOOTER__GET_CONFIGURATION)

    def compute(self) -> list[Effect]:
        """Return the footer configuration that hides the default state buttons."""
        return [NoteFooterConfiguration(hide_default_state_buttons=True).apply()]
