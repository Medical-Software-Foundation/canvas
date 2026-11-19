from canvas_sdk.effects import Effect
from canvas_sdk.effects.note_footer_configuration import NoteFooterConfiguration
from canvas_sdk.events import EventType
from canvas_sdk.handlers.action_button import ActionButton, NoteStateActionButton
from canvas_sdk.handlers.base import BaseHandler
from canvas_sdk.v1.data.note import NoteStates

from supervisor_cosign.helpers.viewer_cosign import note_uuid_for_dbid, viewer_owes_cosign


class CoSignFooterConfiguration(BaseHandler):
    """Hides Canvas's native footer state buttons for the supervisor who owes a co-sign.

    Only the supervisor on a pending record is affected; everyone else, including the
    supervisee, keeps the native footer. CoSignButton and CoSignAmendButton take
    the place of the hidden Sign and Amend/Unlock buttons.
    """

    RESPONDS_TO = [EventType.Name(EventType.NOTE_FOOTER__GET_CONFIGURATION)]

    def compute(self) -> list[Effect]:
        if not viewer_owes_cosign(self.event.target.id, self.event.actor.id):
            return []
        return [NoteFooterConfiguration(hide_default_state_buttons=True).apply()]


class CoSignAmendButton(NoteStateActionButton):
    """Amend/Unlock for the supervisor who owes a co-sign, replacing the hidden native one."""

    STATE_ACTION = NoteStates.UNLOCKED
    BUTTON_KEY = "COSIGN_AMEND_BUTTON"
    PRIORITY = 1

    def compute(self) -> list[Effect]:
        # Native labels the unlock of a signed, signature-required note "Amend".
        context = self._note_context
        if context:
            current_state, is_sig_required, _category = context
            self.BUTTON_TITLE = (
                "Amend" if is_sig_required and current_state == NoteStates.SIGNED else "Unlock"
            )
        # ActionButton.compute, not NoteStateActionButton.compute, keeps the fixed PRIORITY
        # so Co-sign stays first instead of taking the unlock's index in the state matrix.
        return ActionButton.compute(self)

    def visible(self) -> bool:
        if not super().visible():
            return False
        return viewer_owes_cosign(note_uuid_for_dbid(self.event.context.get("note_id")), self.event.actor.id)
