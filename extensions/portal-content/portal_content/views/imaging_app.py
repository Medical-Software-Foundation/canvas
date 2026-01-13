"""Portal application for displaying patient imaging reports."""

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from logger import log
from portal_content.shared.config import is_component_enabled


class ImagingReportsApp(Application):
    """Patient portal application for viewing imaging reports."""

    def on_open(self) -> Effect:
        """Handle the on_open event by launching the imaging reports page."""
        log.info("ImagingReportsApp.on_open() called")

        # Check if this component is enabled
        if not is_component_enabled("imaging", self.secrets):
            log.info("Imaging component is disabled - returning empty")
            return []

        # Get patient ID from context
        user_context = self.event.context.get("user", {})
        patient_id = user_context.get("id")

        if not patient_id:
            patient_context = self.event.context.get("patient", {})
            patient_id = patient_context.get("id")

        if patient_id is None:
            log.warning("Unable to open imaging reports, missing patient id in event context")
            log.warning(f"Full context: {self.event.context}")
            return []

        log.info(f"Opening imaging reports for patient: {patient_id}")

        return LaunchModalEffect(
            url="/plugin-io/api/portal_content/imaging/portal",
            target=LaunchModalEffect.TargetType.PAGE,
        ).apply()
