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
                # The chart modal is dismissed via our own close (X).
                "show_close": True,
            },
        )

        return LaunchModalEffect(
            content=html_content,
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Add Document",
        ).apply()


class PatientDocumentCaptureCompanionApp(PatientDocumentCaptureApp):
    """Provider Companion entry point for the same capture/upload workflow.

    Registered in the manifest with the ``provider_companion_patient_specific``
    scope so it appears as a tab on the patient's page in the Provider Companion.
    It drives the exact same UI (``upload_modal.html``) and backend (``DocumentAPI``)
    as the in-chart app, pre-associated with the current patient.

    The one implementation difference: the Provider Companion modal renders a **URL
    iframe**, not inline HTML, so this entry point points at the plugin's own
    ``GET /documents/ui`` endpoint (which renders the same template server-side)
    instead of passing ``content=``. The in-chart app drawer is unchanged.
    """

    def on_open(self) -> Effect:
        """Launch the same modal in the companion via a served URL iframe."""
        patient_id = self.context.get("patient", {}).get("id", "")
        return LaunchModalEffect(
            url=f"/plugin-io/api/{PLUGIN_NAME}/documents/ui?patient_id={patient_id}",
            target=LaunchModalEffect.TargetType.DEFAULT_MODAL,
            title="Add Document",
        ).apply()

