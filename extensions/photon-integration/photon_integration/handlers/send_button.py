"""Note-footer "Send to Photon" button.

Opens the API-direct send modal, which submits the note's 'Send via Photon'
prescribe commands to Photon with the provider's user token.
"""

from __future__ import annotations

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

SEND_PATH = "/plugin-io/api/photon_integration/photon/send"
# Regenerated on each plugin load so a redeploy busts any cached modal page.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PhotonSendButton(ActionButton):
    """Footer button that launches the Photon API-direct send modal."""

    BUTTON_TITLE = "Send to Photon"
    BUTTON_KEY = "PHOTON_SEND"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_FOOTER

    def handle(self) -> list[Effect]:
        note_id = self.event.context.get("note_id")
        return [
            LaunchModalEffect(
                url=f"{SEND_PATH}?note_id={note_id}&v={_CACHE_BUST}",
                target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE_LARGE,
            ).apply()
        ]
