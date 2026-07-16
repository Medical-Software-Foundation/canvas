import json

from canvas_sdk.clients.aws.libraries import S3
from canvas_sdk.clients.aws.structures import Credentials as S3Credentials
from canvas_sdk.effects import Effect
from canvas_sdk.effects.launch_modal import LaunchModalEffect
from canvas_sdk.handlers.application import Application
from canvas_sdk.templates import render_to_string
from canvas_sdk.v1.data import Patient
from logger import log


class ExternalDocumentsViewerApp(Application):
    """Application handler that opens the external documents viewer in the right chart pane."""

    def _s3_client(self) -> S3:
        return S3(
            S3Credentials(
                key=self.secrets["S3_KEY"],
                secret=self.secrets["S3_SECRET"],
                region=self.secrets["S3_REGION"],
                bucket=self.secrets["S3_BUCKET"],
            )
        )

    def on_open(self) -> Effect:
        # Context is built conditionally by the SDK, so the patient key is not
        # guaranteed to be present even for a patient_specific application.
        patient_id = (self.context.get("patient") or {}).get("id")
        error = None
        notice = None
        documents: list[dict[str, str]] = []
        patient = None

        if not patient_id:
            log.warning("No patient in application context")
            notice = "No external documents available. Contact your administrator for assistance."
        else:
            try:
                patient = Patient.objects.get(id=patient_id)
            except Patient.DoesNotExist:
                log.warning(f"Patient not found: {patient_id}")
                notice = "No external documents available. Contact your administrator for assistance."

        if patient and not notice:
            try:
                client = self._s3_client()
                if not client.is_ready():
                    log.error("S3 client not ready — check S3 secrets configuration")
                    error = "Unable to connect to the document storage service. Please try again later."
                else:
                    prefix = self.secrets.get("S3_PREFIX", "").strip().rstrip("/")
                    base = f"{prefix}/" if prefix else ""
                    index_key = f"{base}patient-indices/{patient_id}.json"
                    log.info(f"Fetching document index: {index_key}")
                    s3_obj = client.access_s3_object(index_key)
                    documents = json.loads(s3_obj.content)["documents"]
                    log.info(f"Found {len(documents)} documents for patient {patient_id}")
                    for doc in documents:
                        full_key = f"{base}{doc['s3_key']}" if base else doc["s3_key"]
                        doc["url"] = client.generate_presigned_url(full_key, expiration=3600) or ""
            except Exception as e:
                log.error(f"Error fetching documents for patient {patient_id}: {e}")
                notice = "No external documents available. Contact your administrator for assistance."

        context = {
            "patient": patient,
            "documents": documents,
            "error": error,
            "notice": notice,
        }
        html = render_to_string("templates/document_viewer.html", context)
        return LaunchModalEffect(
            content=html,
            target=LaunchModalEffect.TargetType.RIGHT_CHART_PANE,
            title="External Documents",
        ).apply()
