"""VitalsApp - portal_menu_item Application handler.

Opens the vitals page in a Canvas portal modal when the patient taps the
"My Vitals" menu item. The page itself is served by ``VitalsAPI``.
"""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log


class VitalsApp(Application):
    """Patient-portal application that launches the vitals page in a modal."""

    def on_open(self) -> Effect | list[Effect]:
        """Resolve the patient id from event context and launch the modal."""
        user_context = self.event.context.get("user", {}) or {}
        patient_context = self.event.context.get("patient", {}) or {}
        patient_id = user_context.get("id") or patient_context.get("id")

        if patient_id is None:
            log.warning(
                "VitalsApp.on_open: missing patient id in event context: %s",
                self.event.context,
            )
            return []

        log.info("VitalsApp.on_open: launching vitals page for patient %s", patient_id)
        return LaunchModalEffect(
            url="/plugin-io/api/patient_vitals/page",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
