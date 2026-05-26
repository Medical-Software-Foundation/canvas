from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton


class CuratedCptFooterButton(ActionButton):
    """Adds an 'Add CPT codes' button to the note footer.

    Clicking the button opens the CPT favorites picker modal, whose contents
    are served by this plugin's `GET /picker` endpoint (see picker_api.py).
    """

    BUTTON_TITLE = "Add CPT codes"
    BUTTON_KEY = "CURATED_CPT_PICKER_OPEN"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_FOOTER

    def handle(self) -> list[Effect]:
        note_id = self.event.context.get("note_id")
        if not note_id:
            return []

        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/curated_cpt_picker/picker?note_id={note_id}",
                target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            ).apply()
        ]
