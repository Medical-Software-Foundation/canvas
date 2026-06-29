from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.action_button import ActionButton

# Module-load timestamp. Changes on every deploy/restart so a fresh modal
# frame URL bypasses the browser's cache.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PanelButton(ActionButton):
    """Note header button to launch the Patient Panel Dashboard."""

    BUTTON_TITLE = "Patient Panel"
    BUTTON_KEY = "OPEN_PATIENT_PANEL"
    BUTTON_LOCATION = ActionButton.ButtonLocation.NOTE_HEADER

    def handle(self) -> list[Effect]:
        """Launch the patient panel modal."""
        return [
            LaunchModalEffect(
                url=f"/plugin-io/api/patient_panel/app/?v={_CACHE_BUST}",
                target=LaunchModalEffect.TargetType.PAGE,
            ).apply()
        ]
