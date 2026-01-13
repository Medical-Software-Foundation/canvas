"""Portal application for displaying patient educational materials."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log
from portal_content.shared.config import is_component_enabled


class EducationMaterialsApp(Application):
    """Patient portal application for viewing educational materials."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching the educational materials page."""
        log.info("EducationMaterialsApp.on_open() called")

        # Check if this component is enabled
        if not is_component_enabled("education", self.secrets):
            log.info("Education component is disabled - returning empty")
            return []

        # Get patient ID from context
        user_context = self.event.context.get("user", {})
        patient_id = user_context.get("id")

        if not patient_id:
            patient_context = self.event.context.get("patient", {})
            patient_id = patient_context.get("id")

        if patient_id is None:
            log.warning("Unable to open educational materials, missing patient id in event context")
            log.warning(f"Full context: {self.event.context}")
            return []

        log.info(f"Opening educational materials for patient: {patient_id}")

        return LaunchModalEffect(
            url="/plugin-io/api/portal_content/education/portal",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
