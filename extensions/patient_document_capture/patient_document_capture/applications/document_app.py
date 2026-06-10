"""App-drawer Application for capturing/uploading a patient document."""

from datetime import datetime, timezone

from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string

from patient_document_capture.utils.constants import PLUGIN_NAME

# Cache bust: generated once at module load, changes on every deploy/restart so the
# browser fetches the latest modal markup.
_CACHE_BUST = str(int(datetime.now(timezone.utc).timestamp()))


class PatientDocumentCaptureApp(Application):
    """Opens the capture/upload modal, pre-associated with the current patient."""

    def on_open(self) -> Effect:
        """Render the capture modal when the app icon is clicked in the chart."""
        patient_id = self.context.get("patient", {}).get("id", "")
        api_base = f"/plugin-io/api/{PLUGIN_NAME}"

        html_content = render_to_string(
            "templates/upload_modal.html",
            {
                "patient_id": patient_id,
                "api_base": api_base,
                "cache_bust": _CACHE_BUST,
            },
        )

        return LaunchModalEffect(
            content=html_content,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Add Document",
        ).apply()
