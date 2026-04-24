from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton
from canvas_sdk.templates import render_to_string

from logger import log


class StickyNoteButton(ActionButton):
    BUTTON_TITLE = "Sticky Note"
    BUTTON_KEY = "STICKY_NOTE"
    BUTTON_LOCATION = ActionButton.ButtonLocation.CHART_PATIENT_HEADER
    BUTTON_BACKGROUND_COLOR = "#feff86"

    def handle(self) -> list[Effect]:
        patient_id = self.event.target.id
        staff_id = self.event.context.get("user", {}).get("id", "")
        auth_token = self.secrets.get("namespace_read_write_access_key", "")

        log.info(
            "StickyNoteButton: opened for patient %s by staff %s"
            % (patient_id, staff_id)
        )

        html = render_to_string(
            "templates/sticky_note.html",
            {
                "patient_id": patient_id,
                "staff_id": staff_id,
                "auth_token": auth_token,
            },
        )

        modal = LaunchModalEffect(
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            content=html,
        )
        return [modal.apply()]
